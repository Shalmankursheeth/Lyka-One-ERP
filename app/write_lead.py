"""
R4 + R5 write path. Backfill and the live-update endpoint both go through here.

Ordering: apply a candidate only if its updated_at is strictly newer than the
row currently stored for that phone_e164. Same-legacy-id updates use:

    UPDATE leads SET ... WHERE lead_id = :id AND updated_at < :candidate_ts
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.models import Lead, LeadMergeLog
from app.normalize import to_utc_naive


def _cmp(dt):
    return to_utc_naive(dt)


class WriteOutcome:
    INSERTED = "inserted"
    UPDATED = "updated"
    SKIPPED_STALE = "skipped_stale"
    MERGED_LOSER = "merged_loser"
    MERGED_WINNER = "merged_winner"


def write_candidate_lead(session, *, legacy_id: str, phone_e164: str, name: str,
                          agent_id, status: str, deal_value, created_at: datetime,
                          updated_at: datetime, now: datetime = None):
    now = to_utc_naive(now or datetime.now(timezone.utc))
    updated_at = to_utc_naive(updated_at)
    created_at = to_utc_naive(created_at)
    existing = session.execute(
        select(Lead).where(Lead.phone_e164 == phone_e164)
    ).scalar_one_or_none()

    if existing is None:
        lead_id = str(uuid.uuid4())
        try:
            with session.begin_nested():
                session.add(Lead(
                    lead_id=lead_id, phone_e164=phone_e164, name=name, agent_id=agent_id,
                    status=status, deal_value=deal_value,
                    created_at=created_at.replace(tzinfo=timezone.utc),
                    updated_at=updated_at.replace(tzinfo=timezone.utc),
                    legacy_id=legacy_id,
                ))
                session.flush()
            return WriteOutcome.INSERTED, lead_id, None
        except IntegrityError:
            existing = session.execute(
                select(Lead).where(Lead.phone_e164 == phone_e164)
            ).scalar_one()

    if existing.legacy_id == legacy_id:
        result = session.execute(
            update(Lead)
            .where(Lead.lead_id == existing.lead_id)
            .where(Lead.updated_at < updated_at.replace(tzinfo=timezone.utc))
            .values(
                name=name,
                agent_id=agent_id,
                status=status,
                deal_value=deal_value,
                created_at=created_at.replace(tzinfo=timezone.utc),
                updated_at=updated_at.replace(tzinfo=timezone.utc),
            )
        )
        session.flush()
        session.refresh(existing)
        if result.rowcount:
            return WriteOutcome.UPDATED, existing.lead_id, None
        return WriteOutcome.SKIPPED_STALE, existing.lead_id, None

    if updated_at > _cmp(existing.updated_at):
        displaced = existing.legacy_id
        if session.get(LeadMergeLog, displaced) is None:
            session.add(LeadMergeLog(
                legacy_id=displaced,
                lead_id=existing.lead_id,
                reason=(
                    f"lost survivorship to legacy_id={legacy_id} on phone {phone_e164}: "
                    f"most-recent updated_at wins "
                    f"({_cmp(existing.updated_at).isoformat()} < {updated_at.isoformat()})"
                ),
                detected_at=now,
            ))
        existing.legacy_id = legacy_id
        existing.name = name
        existing.agent_id = agent_id
        existing.status = status
        existing.deal_value = deal_value
        existing.created_at = created_at.replace(tzinfo=timezone.utc)
        existing.updated_at = updated_at.replace(tzinfo=timezone.utc)
        session.flush()
        return WriteOutcome.MERGED_WINNER, existing.lead_id, displaced

    if session.get(LeadMergeLog, legacy_id) is None:
        session.add(LeadMergeLog(
            legacy_id=legacy_id,
            lead_id=existing.lead_id,
            reason=(
                f"duplicate phone {phone_e164}; most-recent updated_at wins; "
                f"this row's updated_at ({updated_at.isoformat()}) <= surviving "
                f"legacy_id={existing.legacy_id}'s ({_cmp(existing.updated_at).isoformat()})"
            ),
            detected_at=now,
        ))
    session.flush()
    return WriteOutcome.MERGED_LOSER, existing.lead_id, None
