"""Engine. Postgres by default so R5 can commit on a second connection while R6 holds one migration transaction.

SQLite cannot do that: after the migration's first write, a second writer blocks until COMMIT, so T1 never lands inside T0/T2. Set DATABASE_URL to sqlite only for offline unit tests of normalisation — not for the collision.
"""
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.models import Base

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://lyka:lyka@127.0.0.1:5433/lyka",
)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False, "timeout": 30}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    isolation_level="READ COMMITTED",
    pool_pre_ping=True,
)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def reset_db():
    if DATABASE_URL.startswith("sqlite"):
        path = DATABASE_URL.split("sqlite:///")[-1]
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def get_session():
    return SessionLocal()


if __name__ == "__main__":
    reset_db()
    print(f"Reset clean database at {DATABASE_URL}")
