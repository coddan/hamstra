import re
import sqlite3
from datetime import datetime
from pathlib import Path

from ..config import settings

KEEP = 14
NAME = re.compile(r"^(arr|hamstra)-\d{8}-\d{6}\.db$")


def _all() -> list[Path]:
    return [p for p in backup_dir().glob("*.db") if NAME.match(p.name)]


def backup_dir() -> Path:
    d = settings.data_dir / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_file() -> Path | None:
    url = settings.db_url
    return Path(url.replace("sqlite:///", "", 1)) if url.startswith("sqlite:///") else None


def create_backup() -> Path | None:
    """Consistent online copy of the SQLite database (safe while the app is running)."""
    src_path = db_file()
    if not src_path or not src_path.exists():
        return None
    dest = backup_dir() / f"hamstra-{datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(src_path)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    dest.chmod(0o600)
    for old in sorted(_all(), key=lambda p: p.stat().st_mtime)[:-KEEP]:
        old.unlink(missing_ok=True)
    return dest


def list_backups() -> list[dict]:
    return [{"name": p.name, "size": p.stat().st_size, "created": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")}
            for p in sorted(_all(), key=lambda p: p.stat().st_mtime, reverse=True)]


def backup_path(name: str) -> Path | None:
    if not NAME.match(name):
        return None
    p = backup_dir() / name
    return p if p.is_file() else None


def stage_restore(name: str) -> bool:
    """Queue a backup to replace the live database at the next start (see db.apply_pending_restore)."""
    import shutil

    src, live = backup_path(name), db_file()
    if not src or not live:
        return False
    tmp = live.with_name("restore.pending.tmp")
    shutil.copy2(src, tmp)
    tmp.replace(live.with_name("restore.pending"))
    return True
