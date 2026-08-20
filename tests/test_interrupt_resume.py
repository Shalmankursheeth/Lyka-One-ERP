"""R3: crash mid-run then resume; three full runs stay identical."""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import reset_db, get_session
from app.reconcile import build_reconciliation_report
from app.seed_data import seed

PYTHON = sys.executable
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _clean():
    reset_db()
    s = get_session()
    seed(s)
    s.close()


def _migrate(extra):
    subprocess.run(
        [PYTHON, "-m", "app.migrate", *extra],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    )


def test_kill_mid_run_then_resume_converges():
    _clean()
    _migrate(["--batch-size", "50"])
    reference = build_reconciliation_report()
    assert reference["balanced"]
    reference_ledger = {e["legacy_id"]: e["bucket"] for e in reference["ledger"]}

    _clean()
    proc = subprocess.Popen(
        [PYTHON, "-m", "app.migrate", "--batch-size", "1", "--delay-seconds", "1"],
        cwd=REPO_ROOT,
    )
    time.sleep(2.5)
    assert proc.poll() is None, "process exited before interrupt"
    proc.kill()
    proc.wait(timeout=5)

    partial = build_reconciliation_report()
    assert 0 < partial["total_accounted_for"] < 12

    _migrate(["--batch-size", "50"])
    resumed = build_reconciliation_report()
    assert resumed["balanced"]
    resumed_ledger = {e["legacy_id"]: e["bucket"] for e in resumed["ledger"]}
    assert resumed_ledger == reference_ledger


def test_three_complete_runs_are_identical():
    _clean()
    ledgers = []
    for _ in range(3):
        _migrate(["--batch-size", "50"])
        report = build_reconciliation_report()
        assert report["balanced"]
        ledgers.append({e["legacy_id"]: e["bucket"] for e in report["ledger"]})
    assert ledgers[0] == ledgers[1] == ledgers[2]
