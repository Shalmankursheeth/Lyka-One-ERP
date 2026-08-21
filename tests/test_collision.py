"""R5: two processes, one open migration transaction. No in-process hook."""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import get_session, reset_db
from app.models import Lead
from app.seed_data import seed

PYTHON = sys.executable
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _clean():
    reset_db()
    s = get_session()
    seed(s)
    s.close()


def test_backfill_does_not_clobber_live_edit():
    _clean()
    proc = subprocess.Popen(
        [PYTHON, "-m", "app.migrate", "--batch-size", "1", "--delay-seconds", "2"],
        cwd=REPO_ROOT,
    )
    try:
        time.sleep(3)
        assert proc.poll() is None, "migration finished before the live write"
        live = subprocess.run(
            [PYTHON, "-m", "app.live_update", "--legacy-id", "1010", "--status", "Lost"],
            cwd=REPO_ROOT, check=True, capture_output=True, text=True,
        )
        assert "Lost" in live.stdout
        proc.wait(timeout=90)
        assert proc.returncode == 0, f"migrate failed: {proc.returncode}"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    s = get_session()
    lead = s.query(Lead).filter_by(legacy_id="1010").one()
    s.close()
    assert lead.status == "Lost", f"R5 VIOLATION: expected Lost, got {lead.status}"


def test_rerun_does_not_resurrect_stale_status():
    _clean()
    subprocess.run(
        [PYTHON, "-m", "app.migrate", "--batch-size", "50"],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    )
    subprocess.run(
        [PYTHON, "-m", "app.live_update", "--legacy-id", "1010", "--status", "Lost"],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    )
    subprocess.run(
        [PYTHON, "-m", "app.migrate", "--batch-size", "50"],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    )

    s = get_session()
    lead = s.query(Lead).filter_by(legacy_id="1010").one()
    s.close()
    assert lead.status == "Lost"
