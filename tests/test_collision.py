"""R5: live Lost on 1010 must survive the backfill."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import get_session, reset_db
from app.live_update import apply_live_update
from app.migrate import run_migration
from app.models import Lead
from app.seed_data import seed


def _clean():
    reset_db()
    s = get_session()
    seed(s)
    s.close()


def test_backfill_does_not_clobber_live_edit():
    _clean()
    fired = {"done": False}

    def hook(row, candidate):
        if row.id == "1010" and not fired["done"]:
            fired["done"] = True
            apply_live_update("1010", "Lost")

    run_migration(batch_size=1, pre_write_hook=hook)
    assert fired["done"]

    s = get_session()
    lead = s.query(Lead).filter_by(legacy_id="1010").one()
    s.close()
    assert lead.status == "Lost", f"R5 VIOLATION: expected Lost, got {lead.status}"


def test_rerun_does_not_resurrect_stale_status():
    _clean()
    run_migration(batch_size=50)
    apply_live_update("1010", "Lost")
    run_migration(batch_size=50)

    s = get_session()
    lead = s.query(Lead).filter_by(legacy_id="1010").one()
    s.close()
    assert lead.status == "Lost"
