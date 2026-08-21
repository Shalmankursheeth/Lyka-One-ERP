"""
Migration runner. R6: one transaction for the whole run. One COMMIT at the end.

Kill before COMMIT → full rollback. R3 is restart-and-converge: run the source
again; writes are idempotent; final state matches an uninterrupted run.

--batch-size / --delay-seconds only control the T0/T2 sleep window (how often
we pause so a live writer can commit on another connection). They are not
commit boundaries.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from sqlalchemy import select, delete

from app.db import get_session
from app.models import (
    Agent, LeadLegacy, MigrationCursor, MigrationOutcome,
    MigrationWarning, Quarantine,
)
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


def _record_outcome(session, legacy_id, outcome, lead_id, now):
    row = session.get(MigrationOutcome, legacy_id)
    if row is None:
        session.add(MigrationOutcome(
            legacy_id=legacy_id, outcome=outcome, lead_id=lead_id, detected_at=now,
        ))
    else:
        row.outcome = outcome
        row.lead_id = lead_id
        row.detected_at = now


def _record_quarantine(session, legacy_id, raw, reason, now):
    existing = session.execute(
        select(Quarantine).where(Quarantine.legacy_id == legacy_id)
    ).scalar_one_or_none()
    if existing is None:
        session.add(Quarantine(
            legacy_id=legacy_id, raw_row=json.dumps(raw), reason=reason, detected_at=now,
        ))
    else:
        existing.raw_row = json.dumps(raw)
        existing.reason = reason
        existing.detected_at = now


def run_migration(batch_size: int = 50, delay_seconds: float = 0.0, limit: int = None,
                   crash_after_batches: int = None, pre_write_hook=None):
    session = get_session()
    summary = {"migrated": 0, "merged": 0, "quarantined": 0, "skipped_already_done": 0}
    processed_in_batch = 0
    batches_seen = 0

    try:
        valid_agent_ids = {r[0] for r in session.execute(select(Agent.agent_id)).all()}
        ids = [r[0] for r in session.execute(select(LeadLegacy.id).order_by(LeadLegacy.id)).all()]
        if limit:
            ids = ids[:limit]

        for legacy_id in ids:
            row = session.get(LeadLegacy, legacy_id)
            raw = _row_to_dict(row)
            now = to_utc_naive(datetime.now(timezone.utc))
            try:
                candidate, warnings = normalize_legacy_row(row, valid_agent_ids)
                quarantine_reason = None
            except NormalizationError as e:
                candidate, warnings = None, []
                quarantine_reason = e.reason

            # T0 snapshot is `candidate` / `raw` in Python. Sleep without COMMIT.
            processed_in_batch += 1
            if delay_seconds and processed_in_batch >= batch_size:
                time.sleep(delay_seconds)
                processed_in_batch = 0
                batches_seen += 1

            if pre_write_hook and candidate is not None:
                pre_write_hook(row, candidate)

            # See live commits from other connections (Postgres READ COMMITTED).
            session.expire_all()

            if quarantine_reason:
                _record_quarantine(session, legacy_id, raw, quarantine_reason, now)
                _record_outcome(session, legacy_id, "quarantined", None, now)
                summary["quarantined"] += 1
            else:
                outcome, lead_id, displaced = write_candidate_lead(session, now=now, **candidate)
                session.execute(delete(MigrationWarning).where(MigrationWarning.legacy_id == legacy_id))
                for w in warnings:
                    session.add(MigrationWarning(legacy_id=legacy_id, warning=w, detected_at=now))
                if outcome == WriteOutcome.MERGED_LOSER:
                    _record_outcome(session, legacy_id, "merged", lead_id, now)
                    summary["merged"] += 1
                else:
                    _record_outcome(session, legacy_id, "migrated", lead_id, now)
                    summary["migrated"] += 1
                if displaced:
                    _record_outcome(session, displaced, "merged", lead_id, now)
                    if summary["migrated"] > 0:
                        summary["migrated"] -= 1
                        summary["merged"] += 1

            cursor = session.get(MigrationCursor, 1)
            if cursor is None:
                cursor = MigrationCursor(id=1, rows_processed=0)
                session.add(cursor)
            cursor.last_legacy_id = legacy_id
            cursor.rows_processed = (cursor.rows_processed or 0) + 1
            cursor.updated_at = now

            if crash_after_batches is not None and batches_seen >= crash_after_batches:
                raise SystemExit(f"simulated crash after {batches_seen} batch(es), before COMMIT")

        session.commit()
        return summary
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def main():
    ap = argparse.ArgumentParser(description="Lyka One migration runner")
    ap.add_argument(
        "--batch-size", type=int, default=50,
        help="rows between delay sleeps (NOT a commit size; R6 is one transaction)",
    )
    ap.add_argument(
        "--delay-seconds", type=float, default=0.0,
        help="sleep after every --batch-size rows, still inside the open transaction",
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
