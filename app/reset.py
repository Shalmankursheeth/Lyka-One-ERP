"""Documented reset-to-clean: drop schema, recreate, reseed."""
from app.db import reset_db, get_session
from app.seed_data import seed, AGENTS, LEGACY_ROWS


def reset_and_seed():
    reset_db()
    session = get_session()
    seed(session)
    session.close()
    return {"agents": len(AGENTS), "legacy_rows": len(LEGACY_ROWS)}


if __name__ == "__main__":
    result = reset_and_seed()
    print(f"Reset and seeded {result['agents']} agents and {result['legacy_rows']} legacy leads.")
