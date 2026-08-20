"""HTTP wrappers. Live writes hit the new schema only (revised brief)."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.db import reset_db
from app.live_update import apply_live_update
from app.migrate import run_migration
from app.reconcile import build_reconciliation_report
from app.seed_data import seed
from app.db import get_session

app = FastAPI(title="Lyka One Cutover")


class LeadUpdate(BaseModel):
    status: str


@app.post("/api/leads/{legacy_id}/update")
def update_lead(legacy_id: str, body: LeadUpdate):
    try:
        return apply_live_update(legacy_id, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@app.post("/api/migrate")
def http_migrate(batch_size: int = 50, delay_seconds: float = 0.0):
    return run_migration(batch_size=batch_size, delay_seconds=delay_seconds)


@app.get("/api/reconcile")
def http_reconcile():
    return build_reconciliation_report()


@app.post("/api/reset")
def http_reset():
    reset_db()
    session = get_session()
    seed(session)
    session.close()
    return {"status": "reset and reseeded"}
