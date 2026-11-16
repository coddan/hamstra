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
        assert eng.calls == [(24414 * 1024, 6104 * 1024)]
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


def test_import_never_touches_an_unmatched_video_already_in_the_movie_folder(tmp_path: Path):
    from app.models import Movie, QueueItem

    folder = tmp_path / "lib" / "Old Film (1999)"
    folder.mkdir(parents=True)
    mine = folder / "my own rip.mkv"
    mine.write_bytes(b"precious")
    dl = tmp_path / "dl"
    dl.mkdir()
    (dl / "Old.Film.1999.1080p.mkv").write_bytes(b"new")
    with SessionLocal() as db:
        m = Movie(tmdb_id=424242, title="Old Film", year=1999, path=str(folder), has_file=False)
        db.add(m)
        db.flush()
        item = QueueItem(title="Old.Film.1999.1080p", kind="movie", movie_id=m.id, save_path=str(dl))
        db.add(item)
        db.commit()
        assert importer.import_item(db, item, str(dl / "Old.Film.1999.1080p.mkv"))
        assert item.status == "seeding"
        assert mine.read_bytes() == b"precious"
        assert [p.name for p in folder.iterdir()] == ["my own rip.mkv"]


def test_scan_counts_dvd_bluray_and_older_formats_as_existing_files(tmp_path: Path):
    from app.services import scan

    folder = tmp_path / "Film (2001)"
    folder.mkdir()
    for n in ("a.m2ts", "b.divx", "c.mpg", "d.iso", "e.VOB"):
        (folder / n).write_bytes(b"x")
    (folder / "f.sfv").write_bytes(b"x")
    (folder / "g.idx").write_bytes(b"x")
    assert sorted(p.name for p in scan._videos(folder)) == ["a.m2ts", "b.divx", "c.mpg", "d.iso", "e.VOB"]
    only_subs = tmp_path / "Other (2002)"
    only_subs.mkdir()
    (only_subs / "x.idx").write_bytes(b"x")
    (only_subs / "x.sub").write_bytes(b"x")
    assert list(scan._videos(only_subs)) == []
