"""
Schema for the Lyka One cutover.

Target tables match the brief. Extra tables exist so R4 (merged-row
provenance) and operator-facing outcomes are possible without dropping a
losing duplicate. They are written in the same R6 transaction as the leads.
"""
from sqlalchemy import (
    Column, String, Integer, BigInteger, Text, DateTime,
    ForeignKey, UniqueConstraint, CheckConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class LeadLegacy(Base):
    __tablename__ = "leads_legacy"

    id = Column(String, primary_key=True)
    name = Column(String)
    mobile = Column(String)
    agent_code = Column(String)
    status = Column(String)
    deal_value = Column(String)
    created = Column(String)
    updated = Column(String)


class Agent(Base):
    __tablename__ = "agents"

    agent_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)


class Lead(Base):
    __tablename__ = "leads"

    lead_id = Column(String, primary_key=True)
    phone_e164 = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=True)
    status = Column(String, nullable=False)
    deal_value = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    legacy_id = Column(String, nullable=False, unique=True)

    __table_args__ = (
        CheckConstraint(
            "status in ('New','Qualified','Booked','Closed Won','Lost')",
            name="ck_leads_status_enum",
        ),
    )


class Quarantine(Base):
    __tablename__ = "quarantine"

    id = Column(Integer, primary_key=True, autoincrement=True)
    legacy_id = Column(String, nullable=False)
    raw_row = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    detected_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("legacy_id", name="uq_quarantine_legacy_id"),
    )


class MigrationOutcome(Base):
    """Written in the same R6 transaction. Not a durable resume checkpoint."""
    __tablename__ = "migration_outcomes"

    legacy_id = Column(String, primary_key=True)
    outcome = Column(String, nullable=False)
    lead_id = Column(String, nullable=True)
    detected_at = Column(DateTime(timezone=True), nullable=False)


class LeadMergeLog(Base):
    __tablename__ = "lead_merge_log"

    legacy_id = Column(String, primary_key=True)
    lead_id = Column(String, ForeignKey("leads.lead_id"), nullable=False)
    reason = Column(Text, nullable=False)
    detected_at = Column(DateTime(timezone=True), nullable=False)


class MigrationWarning(Base):
    __tablename__ = "migration_warnings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    legacy_id = Column(String, nullable=False)
    warning = Column(Text, nullable=False)
    detected_at = Column(DateTime(timezone=True), nullable=False)


class MigrationCursor(Base):
    __tablename__ = "migration_cursor"

    id = Column(Integer, primary_key=True)
    last_legacy_id = Column(String, nullable=True)
    rows_processed = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=True)
