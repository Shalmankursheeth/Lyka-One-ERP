"""Engine, WAL, and the reset-to-clean command."""
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.models import Base

DB_PATH = os.environ.get(
    "LYKA_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "lyka.db"),
)
DB_PATH = os.path.abspath(DB_PATH)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def reset_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def get_session():
    return SessionLocal()


if __name__ == "__main__":
    reset_db()
    print(f"Reset clean database at {DB_PATH}")
