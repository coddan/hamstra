from pathlib import Path

from app.db import SessionLocal
from app.models import Setting
from app.services import grab, importer, seeding
from app.services.decision import meets_cutoff


def test_place_keeps_existing_file_unless_overwrite(tmp_path: Path):
    src, dest = tmp_path / "new.mkv", tmp_path / "lib" / "old.mkv"
    src.write_bytes(b"new")
    dest.parent.mkdir()
    dest.write_bytes(b"old")
    assert importer.place(src, dest, "copy", overwrite=False) == "kept"
    assert dest.read_bytes() == b"old"
    importer.place(src, dest, "copy")
    assert dest.read_bytes() == b"new"


def test_existing_files_are_never_wanted_when_protected():
    assert meets_cutoff(True, 720, 1080, upgrade_allowed=False)
    assert not meets_cutoff(True, 720, 1080, upgrade_allowed=True)
    assert not meets_cutoff(False, None, 1080, upgrade_allowed=False)


def test_protect_existing_defaults_on_and_disables_upgrades():
    with SessionLocal() as db:
        assert seeding.download_rules(db)["protect_existing"] is True
        assert grab.profile_for(db, None).upgrade_allowed is False


class FakeEngine:
    def __init__(self):
        self.calls = []

    def set_limits(self, down, up):
        self.calls.append((down, up))


def test_speed_limits_are_applied_once_per_change():
    import json

    eng = FakeEngine()
    with SessionLocal() as db:
        seeding.apply_limits(db, eng)
        assert eng.calls == [(0, 0)]
        seeding.apply_limits(db, eng)
        assert len(eng.calls) == 1
        db.merge(Setting(key="downloads", value=json.dumps({"max_download_kbps": 500, "max_upload_kbps": 100})))
        db.commit()
        seeding.apply_limits(db, eng)
        assert eng.calls[-1] == (500 * 1024, 100 * 1024)
        db.query(Setting).filter_by(key="downloads").delete()
        db.commit()


def test_wanted_lists_only_what_is_missing_and_toggles_work():
    from datetime import date, timedelta

    from fastapi.testclient import TestClient

    from app.main import app
    from app.models import Episode, Series

    today = date.today()
    with TestClient(app) as c, SessionLocal() as db:
        s = Series(tvmaze_id=987001, title="Wanted Show", monitored=True)
        s.episodes = [Episode(season=1, number=1, air_date=today - timedelta(days=9), monitored=True),
                      Episode(season=1, number=2, air_date=today - timedelta(days=2), monitored=True, file_path="/x/e2.mkv"),
                      Episode(season=1, number=3, air_date=today + timedelta(days=5), monitored=True),
                      Episode(season=1, number=4, air_date=today - timedelta(days=1), monitored=False)]
        done = Series(tvmaze_id=987002, title="Complete Show", monitored=True)
        done.episodes = [Episode(season=1, number=1, air_date=today - timedelta(days=9), monitored=True, file_path="/x/a.mkv")]
        off = Series(tvmaze_id=987003, title="Off Show", monitored=False)
        off.episodes = [Episode(season=1, number=1, air_date=today - timedelta(days=9), monitored=True)]
        db.add_all([s, done, off])
        db.commit()
        sid, eid = s.id, s.episodes[3].id

        data = c.get("/api/v1/wanted").json()
        row = {r["title"]: r for r in data["series"]}
        assert row["Wanted Show"]["missing"] == 1 and row["Wanted Show"]["upcoming"] == 1
        assert row["Wanted Show"]["next_air"] == (today + timedelta(days=5)).isoformat()
        assert row["Complete Show"]["missing"] == 0
        assert "Off Show" not in row

        r = c.patch(f"/api/v1/series/{sid}/episodes/{eid}", json={"monitored": True})
        assert r.status_code == 200 and r.json()["monitored"] is True
        assert c.patch(f"/api/v1/series/{sid + 999}/episodes/{eid}", json={"monitored": True}).status_code == 404
        r = c.patch(f"/api/v1/series/{sid}/seasons/1", json={"monitored": False})
        assert r.json()["changed"] == 4
        row = {r["title"]: r for r in c.get("/api/v1/wanted").json()["series"]}
        assert row["Wanted Show"]["missing"] == 0 and row["Wanted Show"]["upcoming"] == 0
