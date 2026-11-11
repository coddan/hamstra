import sqlite3

from app.config import settings
from app.services import backup


def make_db(path, value):
    c = sqlite3.connect(path)
    c.execute("create table if not exists t (v text)")
    c.execute("delete from t")
    c.execute("insert into t values (?)", (value,))
    c.commit()
    c.close()


def read(path):
    c = sqlite3.connect(path)
    try:
        return c.execute("select v from t").fetchone()[0]
    finally:
        c.close()


def test_stage_and_apply_restore(tmp_path, monkeypatch):
    from app import db as dbmod

    live = tmp_path / "arr.db"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{live}")
    make_db(live, "current")
    (tmp_path / "backups").mkdir()
    old = tmp_path / "backups" / "arr-20250101-000000.db"
    make_db(old, "from backup")

    assert backup.stage_restore("arr-20250101-000000.db") is True
    assert (tmp_path / "restore.pending").exists() and read(live) == "current"        # nothing changes until the next start
    assert backup.stage_restore("../../etc/passwd") is False and backup.stage_restore("arr-19990101-000000.db") is False

    assert dbmod.apply_pending_restore() == str(live)
    assert read(live) == "from backup" and not (tmp_path / "restore.pending").exists()
    kept = [p for p in (tmp_path / "backups").glob("*.db") if p != old]
    assert len(kept) == 1 and read(kept[0]) == "current"                               # the replaced database is kept
    assert dbmod.apply_pending_restore() is None                                       # nothing pending any more
