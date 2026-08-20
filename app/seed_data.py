"""Seed exactly the brief data. Row 1009 name contains U+00A0, not a space."""
from app.models import Agent, LeadLegacy

AGENTS = [
    ("AG01", "Ravi Kumar"),
    ("AG02", "Priya Menon"),
    ("AG03", "Bikash Thapa"),
    ("AG04", "Deepa Reddy"),
    ("AG05", "Anand Raj"),
]

LEGACY_ROWS = [
    ("1001", "Ravi Client", "+971 50 111 2222", "AG01", "Closed Won", "AED 1,200,000", "2026-07-01", "2026-08-01T09:00:00Z"),
    ("1002", " ravi client ", "0501112222", "AG01", "Closed Won", "1200000", "2026-07-01", "2026-08-05T09:00:00Z"),
    ("1003", "Meera K", "+971 55 222 3344", "AG02", "Qualified", "", "19/07/2026", "2026-08-02T09:00:00Z"),
    ("1004", "Tariq H", "+971 52 333 4455", "AG99", "New", "", "2026-08-10", "2026-08-10T09:00:00Z"),
    ("1005", "Nisha P", "+971 54 444 5566", "AG03", "Booked", "AED 850,000", "01-02-2026", "2026-08-03T09:00:00Z"),
    ("1006", "Arun G", "00971509876543", "AG02", "Closed Won", "AED 2,000,000", "2026-06-15", "2026-08-04T09:00:00Z"),
    ("1007", "Zainab R", "+971 56 777 8899", "AG03", "", "AED 640,000", "2026-07-20", "2026-08-06T09:00:00Z"),
    ("1008", "Muhammed Shanil", "+971 58 121 2121", "AG04", "Meeting Done", "", "2026-08-01", "2026-08-07T09:00:00Z"),
    ("1009", "Muhammed\u00A0Shanil", "+971 58 121 2121", "AG04", "Booked", "", "2026-08-01", "2026-08-09T09:00:00Z"),
    ("1010", "Kiran D", "+971 55 999 0000", "AG01", "Closed Won", "AED 990,000", "2026-05-10", "2026-08-08T09:00:00Z"),
    ("1011", "Fatima A", "971561112233", "AG05", "Qualified", "", "2026-08-12", "2026-08-12T09:00:00Z"),
    ("1012", "Omar K", "+971 50 333", "AG02", "New", "", "2026-08-13", "2026-08-13T09:00:00Z"),
]


def seed(session):
    for agent_id, name in AGENTS:
        session.merge(Agent(agent_id=agent_id, name=name))
    for row in LEGACY_ROWS:
        (id_, name, mobile, agent_code, status, deal_value, created, updated) = row
        session.merge(LeadLegacy(
            id=id_, name=name, mobile=mobile, agent_code=agent_code,
            status=status, deal_value=deal_value, created=created, updated=updated,
        ))
    session.commit()


if __name__ == "__main__":
    from app.db import reset_db, get_session
    reset_db()
    s = get_session()
    seed(s)
    s.close()
    print(f"Seeded {len(AGENTS)} agents and {len(LEGACY_ROWS)} legacy leads.")
