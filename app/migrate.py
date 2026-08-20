"""
Migration runner.

R3: migration_outcomes is the resume cursor. Kill mid-run; restart; skip
legacy_ids already decided. Three complete runs match one.

R6 is per row (one transaction per legacy_id), not one transaction for the
whole run — see NOTES.md Q4.

The T0 snapshot lives in Python. The T2 write uses a new SQLite session
opened after the delay, so a live edit committed on another connection is
visible (a long-lived WAL snapshot would hide it).

CLI:
    python -m app.migrate --batch-size 1 [--delay-seconds 3]
"""
import argparse
import json
import time
from datetime import datetime, timezone
from sqlalchemy import select

from app.db import get_session
from app.models import LeadLegacy, MigrationOutcome, MigrationWarning, Quarantine, MigrationCursor, Agent
from app.normalize import (
    normalize_name, normalize_phone, normalize_deal_value,
    normalize_date_to_dubai, normalize_status, to_utc_naive, NormalizationError,
)
from app.write_lead import write_candidate_lead, WriteOutcome


def _row_to_dict(row: LeadLegacy) -> dict:
    return {
        "id": row.id, "name": row.name, "mobile": row.mobile,
        "agent_code": row.agent_code, "status": row.status,
        "deal_value": row.deal_value, "created": row.created, "updated": row.updated,
    }


def normalize_legacy_row(row: LeadLegacy, valid_agent_ids: set):
    warnings = []
    name = normalize_name(row.name)
    phone = normalize_phone(row.mobile)
    status = normalize_status(row.status)
    deal_value = normalize_deal_value(row.deal_value)
    created_at = to_utc_naive(normalize_date_to_dubai(row.created))
    updated_at = to_utc_naive(normalize_date_to_dubai(row.updated))

    agent_id = row.agent_code
    if agent_id is not None and agent_id.strip() != "":
        if agent_id not in valid_agent_ids:
            warnings.append(
                f"agent_code '{agent_id}' does not match any row in agents; "
                f"lead migrated with agent_id=NULL (unassigned pool)"
            )
            agent_id = None
    else:
        agent_id = None

    return dict(
        legacy_id=row.id, phone_e164=phone, name=name, agent_id=agent_id,
        status=status, deal_value=deal_value, created_at=created_at, updated_at=updated_at,
    ), warnings


def run_migration(batch_size: int = 50, delay_seconds: float = 0.0, limit: int = None,
                   crash_after_batches: int = None, pre_write_hook=None):
    read = get_session()
    already_done = {r[0] for r in read.execute(select(MigrationOutcome.legacy_id)).all()}
    valid_agent_ids = {r[0] for r in read.execute(select(Agent.agent_id)).all()}
    ids = [r[0] for r in read.execute(select(LeadLegacy.id).order_by(LeadLegacy.id)).all()]
    read.close()
    if limit:
        ids = ids[:limit]
    pending = [i for i in ids if i not in already_done]

    summary = {
        "migrated": 0, "merged": 0, "quarantined": 0,
        "skipped_already_done": len(ids) - len(pending),
    }
    batches_committed = 0
    pending_in_batch = 0

    for legacy_id in pending:
        # --- T0: snapshot on a short-lived read session, then close it ---
        snap = get_session()
        row = snap.get(LeadLegacy, legacy_id)
        raw = _row_to_dict(row)
        try:
            candidate, warnings = normalize_legacy_row(row, valid_agent_ids)
            quarantine_reason = None
        except NormalizationError as e:
            candidate, warnings = None, []
            quarantine_reason = e.reason
        snap.close()

        if delay_seconds:
            time.sleep(delay_seconds)
        if pre_write_hook and candidate is not None:
            pre_write_hook(row, candidate)

        # --- T2: fresh write session, sees live commits from other processes ---
        now = to_utc_naive(datetime.now(timezone.utc))
        write = get_session()
        try:
            if quarantine_reason:
                write.add(Quarantine(
                    legacy_id=legacy_id,
                    raw_row=json.dumps(raw),
                    reason=quarantine_reason,
                    detected_at=now,
                ))
                write.add(MigrationOutcome(
                    legacy_id=legacy_id, outcome="quarantined", lead_id=None, detected_at=now,
                ))
                summary["quarantined"] += 1
            else:
                outcome, lead_id, displaced = write_candidate_lead(write, now=now, **candidate)
                for w in warnings:
                    write.add(MigrationWarning(legacy_id=legacy_id, warning=w, detected_at=now))
                if outcome == WriteOutcome.MERGED_LOSER:
                    write.add(MigrationOutcome(
                        legacy_id=legacy_id, outcome="merged", lead_id=lead_id, detected_at=now,
                    ))
                    summary["merged"] += 1
                else:
                    write.add(MigrationOutcome(
                        legacy_id=legacy_id, outcome="migrated", lead_id=lead_id, detected_at=now,
                    ))
                    summary["migrated"] += 1
                if displaced:
                    prior = write.get(MigrationOutcome, displaced)
                    if prior is not None:
                        prior.outcome = "merged"
                        summary["migrated"] -= 1
                        summary["merged"] += 1

            cursor = write.get(MigrationCursor, 1)
            if cursor is None:
                cursor = MigrationCursor(id=1, rows_processed=0)
                write.add(cursor)
            cursor.last_legacy_id = legacy_id
            cursor.rows_processed = (cursor.rows_processed or 0) + 1
            cursor.updated_at = now
            write.commit()
        except Exception:
            write.rollback()
            raise
        finally:
            write.close()

        pending_in_batch += 1
        if pending_in_batch >= batch_size:
            batches_committed += 1
            pending_in_batch = 0
            if crash_after_batches is not None and batches_committed >= crash_after_batches:
                raise SystemExit(f"simulated crash after {batches_committed} batch(es)")

    return summary


def main():
    ap = argparse.ArgumentParser(description="Lyka One migration runner")
    ap.add_argument("--batch-size", type=int, default=50)
    ap.add_argument(
        "--delay-seconds", type=float, default=0.0,
        help="sleep after reading each row and before writing it (R5 window)",
    )
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--crash-after-batches", type=int, default=None)
    args = ap.parse_args()
    print(json.dumps(run_migration(
        batch_size=args.batch_size,
        delay_seconds=args.delay_seconds,
        limit=args.limit,
        crash_after_batches=args.crash_after_batches,
    ), indent=2, default=str))


if __name__ == "__main__":
    main()
