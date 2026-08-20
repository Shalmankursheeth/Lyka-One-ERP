"""R7 — every legacy row in exactly one bucket: migrated, merged, or quarantined."""
import json
from sqlalchemy import select
from app.db import get_session
from app.models import LeadLegacy, Lead, Quarantine, LeadMergeLog, MigrationWarning


def build_reconciliation_report():
    session = get_session()

    legacy_rows = session.execute(select(LeadLegacy).order_by(LeadLegacy.id)).scalars().all()
    leads_by_legacy_id = {l.legacy_id: l for l in session.execute(select(Lead)).scalars().all()}
    merge_log = {m.legacy_id: m for m in session.execute(select(LeadMergeLog)).scalars().all()}
    quarantine = {q.legacy_id: q for q in session.execute(select(Quarantine)).scalars().all()}
    warnings_by_legacy = {}
    for w in session.execute(select(MigrationWarning)).scalars().all():
        warnings_by_legacy.setdefault(w.legacy_id, []).append(w.warning)

    ledger = []
    counts = {"migrated": 0, "merged": 0, "quarantined": 0, "unaccounted": 0}

    for row in legacy_rows:
        entry = {"legacy_id": row.id, "warnings": warnings_by_legacy.get(row.id, [])}
        if row.id in leads_by_legacy_id:
            lead = leads_by_legacy_id[row.id]
            entry["bucket"] = "migrated"
            entry["lead_id"] = lead.lead_id
            entry["phone_e164"] = lead.phone_e164
            counts["migrated"] += 1
        elif row.id in merge_log:
            m = merge_log[row.id]
            entry["bucket"] = "merged"
            entry["merged_into_lead_id"] = m.lead_id
            entry["reason"] = m.reason
            counts["merged"] += 1
        elif row.id in quarantine:
            q = quarantine[row.id]
            entry["bucket"] = "quarantined"
            entry["reason"] = q.reason
            counts["quarantined"] += 1
        else:
            entry["bucket"] = "UNACCOUNTED"
            counts["unaccounted"] += 1
        ledger.append(entry)

    total_legacy = len(legacy_rows)
    total_accounted = counts["migrated"] + counts["merged"] + counts["quarantined"]

    report = {
        "total_legacy_rows": total_legacy,
        "total_leads_in_target": len(leads_by_legacy_id),
        "counts": counts,
        "total_accounted_for": total_accounted,
        "balanced": total_accounted == total_legacy and counts["unaccounted"] == 0,
        "ledger": ledger,
    }
    session.close()
    return report


def print_report():
    report = build_reconciliation_report()
    print(json.dumps(report, indent=2, default=str))
    print()
    status = "BALANCED" if report["balanced"] else "*** NOT BALANCED -- INVESTIGATE ***"
    print(
        f"{report['total_legacy_rows']} legacy rows -> "
        f"{report['counts']['migrated']} migrated + "
        f"{report['counts']['merged']} merged + "
        f"{report['counts']['quarantined']} quarantined "
        f"= {report['total_accounted_for']} accounted for.  [{status}]"
    )


if __name__ == "__main__":
    print_report()
