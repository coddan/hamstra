from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

def apply_pending_restore() -> str | None:
    """A restore is staged as <data>/restore.pending and applied here, before the database is opened.
    The database being replaced is kept as a normal backup, so a restore can always be undone."""
    import shutil
    from datetime import datetime
    from pathlib import Path

    if not settings.db_url.startswith("sqlite:///"):
        return None
    db_path = Path(settings.db_url.replace("sqlite:///", "", 1))
    pending = db_path.with_name("restore.pending")
    if not pending.exists():
        return None
    backups = db_path.parent / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        shutil.copy2(db_path, backups / f"hamstra-{datetime.now():%Y%m%d-%H%M%S}.db")
    for suffix in ("-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    shutil.move(str(pending), db_path)
    return str(db_path)


RESTORED = apply_pending_restore()
engine = create_engine(settings.db_url, connect_args={"check_same_thread": False, "timeout": 30})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    if settings.db_url.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")   # readers no longer block the writer: avoids "database is locked"
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

