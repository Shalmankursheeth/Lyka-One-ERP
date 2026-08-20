"""Minimal write path into the new schema — not a dual-write proxy."""
import argparse
import json
from datetime import datetime, timezone
from sqlalchemy import select

from app.db import get_session
from app.models import Agent, Lead, LeadLegacy
from app.normalize import (
    NormalizationError, normalize_date_to_dubai, normalize_deal_value,
    normalize_name, normalize_phone, normalize_status, to_utc_naive,
)
from app.write_lead import write_candidate_lead


def apply_live_update(legacy_id: str, status: str) -> dict:
    session = get_session()
    now = to_utc_naive(datetime.now(timezone.utc))
    try:
        status = normalize_status(status)
        legacy = session.get(LeadLegacy, legacy_id)
        if legacy is None:
            raise ValueError(f"no legacy row with id {legacy_id}")

        existing = session.execute(
            select(Lead).where(Lead.legacy_id == legacy_id)
        ).scalar_one_or_none()

        if existing is None:
            try:
                phone = normalize_phone(legacy.mobile)
            except NormalizationError as e:
                raise ValueError(f"cannot live-update {legacy_id}: {e.reason}") from e
            existing = session.execute(
                select(Lead).where(Lead.phone_e164 == phone)
            ).scalar_one_or_none()

        valid_agent_ids = {r[0] for r in session.execute(select(Agent.agent_id)).all()}

        if existing is not None:
            candidate = dict(
                legacy_id=existing.legacy_id,
                phone_e164=existing.phone_e164,
                name=existing.name,
                agent_id=existing.agent_id,
                status=status,
                deal_value=existing.deal_value,
                created_at=existing.created_at,
                updated_at=now,
            )
        else:
            agent_id = legacy.agent_code if legacy.agent_code in valid_agent_ids else None
            candidate = dict(
                legacy_id=legacy.id,
                phone_e164=normalize_phone(legacy.mobile),
                name=normalize_name(legacy.name),
                agent_id=agent_id,
                status=status,
                deal_value=normalize_deal_value(legacy.deal_value),
                created_at=to_utc_naive(normalize_date_to_dubai(legacy.created)),
                updated_at=now,
            )

        outcome, lead_id, _displaced = write_candidate_lead(session, now=now, **candidate)
        session.commit()
        lead = session.get(Lead, lead_id)
        return {
            "legacy_id": legacy_id,
            "lead_id": lead_id,
            "outcome": outcome,
            "status": lead.status,
            "updated_at": lead.updated_at.isoformat(),
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main():
    ap = argparse.ArgumentParser(description="Live update against the new schema only")
    ap.add_argument("--legacy-id", required=True)
    ap.add_argument("--status", required=True)
    args = ap.parse_args()
    print(json.dumps(apply_live_update(args.legacy_id, args.status), indent=2))


if __name__ == "__main__":
    main()
