"""
R4 + R5 write path. Backfill and the live-update endpoint both go through here.

Ordering: apply a candidate only if its updated_at is strictly newer than the
row currently stored for that phone_e164. The UPDATE uses a WHERE on
updated_at so a stale snapshot cannot clobber a live edit that landed after
the backfill read the legacy row.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, update
from app.models import Lead, LeadMergeLog


class WriteOutcome:
    INSERTED = "inserted"
    UPDATED = "updated"
    SKIPPED_STALE = "skipped_stale"
    MERGED_LOSER = "merged_loser"
    MERGED_WINNER = "merged_winner"


def write_candidate_lead(session, *, legacy_id: str, phone_e164: str, name: str,
                          agent_id, status: str, deal_value, created_at: datetime,
                          updated_at: datetime, now: datetime = None):
    now = now or datetime.now(timezone.utc)
    existing = session.execute(
        select(Lead).where(Lead.phone_e164 == phone_e164)
    ).scalar_one_or_none()

    if existing is None:
        lead_id = str(uuid.uuid4())
        session.add(Lead(
            lead_id=lead_id, phone_e164=phone_e164, name=name, agent_id=agent_id,
            status=status, deal_value=deal_value, created_at=created_at,
            updated_at=updated_at, legacy_id=legacy_id,
        ))
        session.flush()
        return WriteOutcome.INSERTED, lead_id, None

    if existing.legacy_id == legacy_id:
        result = session.execute(
            update(Lead)
            .where(Lead.lead_id == existing.lead_id)
            .where(Lead.updated_at < updated_at)
            .values(
                name=name,
                agent_id=agent_id,
                status=status,
                deal_value=deal_value,
                created_at=created_at,
                updated_at=updated_at,
            )
        )
        session.flush()
        session.refresh(existing)
        if result.rowcount:
            return WriteOutcome.UPDATED, existing.lead_id, None
        return WriteOutcome.SKIPPED_STALE, existing.lead_id, None

    if updated_at > existing.updated_at:
        displaced = existing.legacy_id
        session.add(LeadMergeLog(
            legacy_id=displaced,
            lead_id=existing.lead_id,
            reason=(
                f"lost survivorship to legacy_id={legacy_id} on phone {phone_e164}: "
                f"most-recent updated_at wins "
                f"({existing.updated_at.isoformat()} < {updated_at.isoformat()})"
            ),
            detected_at=now,
        ))
        existing.legacy_id = legacy_id
        existing.name = name
        existing.agent_id = agent_id
        existing.status = status
        existing.deal_value = deal_value
        existing.created_at = created_at
        existing.updated_at = updated_at
        session.flush()
        return WriteOutcome.MERGED_WINNER, existing.lead_id, displaced

    session.add(LeadMergeLog(
        legacy_id=legacy_id,
        lead_id=existing.lead_id,
        reason=(
            f"duplicate phone {phone_e164}; most-recent updated_at wins; "
            f"this row's updated_at ({updated_at.isoformat()}) <= surviving "
            f"legacy_id={existing.legacy_id}'s ({existing.updated_at.isoformat()})"
        ),
        detected_at=now,
    ))
    session.flush()
    return WriteOutcome.MERGED_LOSER, existing.lead_id, None
