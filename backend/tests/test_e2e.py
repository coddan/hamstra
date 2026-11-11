"""End to end: search -> decide -> grab -> download (fake engine) -> import -> library updated."""
from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.engines import factory
from app.engines.base import TorrentStatus
from app.indexers.torznab import Result
from app.main import app
from app.models import Episode, Movie, RootFolder, Series


class FakeEngine:
    def __init__(self, downloads):
        self.downloads, self.added, self.done, self.stat = downloads, {}, False, (0.0, 0)

    def add(self, url, save_path, category="arr"):
        self.added[url] = "a" * 40
        return "a" * 40

    def list(self):
        return [TorrentStatus("a" * 40, "x", 1.0 if self.done else 0.4, "downloading", str(self.downloads / "rel"),
                              ratio=self.stat[0], seeding_seconds=self.stat[1])]

    def add_file(self, data, save_path, category="arr"):
        return None  # the app then derives the info hash from the file itself

    def remove(self, *a, **k): pass
    def pause(self, *a): pass
    def resume(self, *a): pass


def test_full_flow(tmp_path, monkeypatch):
    dl = tmp_path / "dl"
    (dl / "rel").mkdir(parents=True)
    (dl / "rel" / "The.Matrix.1999.1080p.BluRay.x264-G.mkv").write_text("video")
    (dl / "rel" / "Sample.mkv").write_text("s")
    monkeypatch.setattr(settings, "downloads_dir", dl)
    eng = FakeEngine(dl)
    factory.set_engine(eng)

    def fake_search(db, query, mode="search", season=None, episode=None, year=None, categories="", **kw):
        if mode == "movie":
            return [
                Result("The.Matrix.1999.CAM.x264-G", "ix", "magnet:?xt=urn:btih:" + "b" * 40, "b" * 40, 1_000_000, 50),
                Result("The.Matrix.1999.1080p.BluRay.x264-G", "ix", "magnet:?xt=urn:btih:" + "a" * 40, "a" * 40, 8_000_000_000, 40),
            ], []
        return [], []
    monkeypatch.setattr("app.indexers.manager.search_all", fake_search)

    with TestClient(app) as c:
        with SessionLocal() as db:
            for m in db.query(Movie).all():
                db.delete(m)
            root = RootFolder(path=str(tmp_path / "movies"), kind="movies_adults")
            db.add(root)
            db.flush()
            db.add(Movie(tmdb_id=603, title="The Matrix", year=1999, root_folder_id=root.id,
                         path=str(tmp_path / "movies" / "The Matrix (1999)")))
            db.commit()
            mid = db.query(Movie).first().id

        rel = c.get(f"/api/v1/movies/{mid}/releases").json()["releases"]
        assert rel[0]["accepted"] and rel[0]["resolution"] == 1080
        assert any("cam/telesync" in r["reasons"] for r in rel)

        assert c.post(f"/api/v1/movies/{mid}/search").json()["grabbed"] == "The.Matrix.1999.1080p.BluRay.x264-G"
        assert c.post(f"/api/v1/movies/{mid}/search").json()["grabbed"] is None  # already queued
        assert c.get("/api/v1/queue").json()[0]["status"] == "downloading"

        c.post("/api/v1/commands/sync-queue")
        assert 0.3 < c.get("/api/v1/queue").json()[0]["progress"] < 0.5

        eng.done = True
        assert c.post("/api/v1/commands/sync-queue").json()["imported"] == 1
        dest = tmp_path / "movies" / "The Matrix (1999)" / "The Matrix (1999).mkv"
        assert dest.read_text() == "video"
        m = [x for x in c.get("/api/v1/movies").json() if x["id"] == mid][0]
        assert m["has_file"]
        assert c.get("/api/v1/history").json()[0]["event"] == "imported"
        q = c.get("/api/v1/queue").json()
        assert q[0]["status"] == "seeding"
        assert dest.exists() and (dl / "rel").exists()  # still seeding, original kept

        # seeding rules not met -> kept; met -> removed from client and marked cleaned
        removed = []
        eng.remove = lambda h, delete_files=False: removed.append((h, delete_files))
        eng.stat = (0.2, 3600)
        c.post("/api/v1/commands/sync-queue")
        assert removed == []
        eng.stat = (1.5, 3600)
        assert c.post("/api/v1/commands/sync-queue").json()["cleaned"] == 1
        assert removed == [("a" * 40, True)]
        assert c.get("/api/v1/queue").json() == []
        assert c.get("/api/v1/history").json()[0]["event"] == "removed"

    factory.set_engine(None)


def test_episode_import(tmp_path, monkeypatch):
    dl = tmp_path / "dl"
    (dl / "rel").mkdir(parents=True)
    (dl / "rel" / "Show.Name.S01E02.720p.HDTV.x264-G.mkv").write_text("ep")
    monkeypatch.setattr(settings, "downloads_dir", dl)
    factory.set_engine(FakeEngine(dl))
    eng = factory._override
    eng.done = True
    with TestClient(app) as c, SessionLocal() as db:
        s = Series(tvmaze_id=999, title="Show Name", year=2020, path=str(tmp_path / "tv" / "Show Name (2020)"))
        s.episodes += [Episode(season=1, number=1), Episode(season=1, number=2, title="Two")]
        db.add(s)
        db.commit()
        e2 = [e for e in s.episodes if e.number == 2][0]
        r = c.post("/api/v1/grab", json={"title": "Show.Name.S01E02.720p.HDTV.x264-G", "download_url": "magnet:x",
                                         "series_id": s.id, "episode_id": e2.id})
        assert r.status_code == 201
        assert c.post("/api/v1/commands/sync-queue").json()["imported"] == 1
        db.expire_all()
        assert db.get(Episode, e2.id).file_path.endswith("Season 01/Show Name - S01E02 - Two.mkv")
        assert db.get(Episode, e2.id).file_resolution == 720
    factory.set_engine(None)


def test_auth(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/v1/movies").status_code == 401
        assert c.get("/api/v1/movies", headers={"x-api-key": "secret"}).status_code == 200


def test_season_pack_import(tmp_path, monkeypatch):
    dl = tmp_path / "dl"
    pack = dl / "Show.Pack.S01.1080p.WEB-DL.x264-G"
    pack.mkdir(parents=True)
    for n in (1, 2, 3):
        (pack / f"Show.Pack.S01E0{n}.1080p.WEB-DL.x264-G.mkv").write_text(f"ep{n}")
    (pack / "Show.Pack.S01E04.1080p.WEB-DL.x264-G.mkv").write_text("not wanted")
    (pack / "info.nfo").write_text("x")
    monkeypatch.setattr(settings, "downloads_dir", dl)
    eng = FakeEngine(dl)
    eng.done = True
    eng.list = lambda: [TorrentStatus("a" * 40, "x", 1.0, "downloading", str(pack))]
    factory.set_engine(eng)
    with TestClient(app) as c, SessionLocal() as db:
        s = Series(tvmaze_id=777, title="Show Pack", year=2021, path=str(tmp_path / "tv" / "Show Pack (2021)"))
        s.episodes += [Episode(season=1, number=n) for n in (1, 2, 3, 4)]
        db.add(s)
        db.commit()
        wanted = [e for e in s.episodes if e.number <= 3]
        from app.services import grab
        item = grab.grab(db, Result("Show.Pack.S01.1080p.WEB-DL.x264-G", "m", "magnet:x", "a" * 40), "episode",
                         series=s, episodes=wanted)
        assert c.post("/api/v1/commands/sync-queue").json()["imported"] == 1
        db.expire_all()
        have = {e.number: e.has_file for e in db.get(Series, s.id).episodes}
        assert have == {1: True, 2: True, 3: True, 4: False}
    factory.set_engine(None)


def test_torznab_id_search_with_fallback(monkeypatch):
    from types import SimpleNamespace

    from app.indexers import torznab

    calls = []

    def fake_fetch(ix, params):
        calls.append(params)
        return [] if "imdbid" in params else [Result("Hit", "ix", "magnet:x")]

    monkeypatch.setattr(torznab, "_fetch", fake_fetch)
    ix = SimpleNamespace(kind="torznab", url="u", api_key="k", categories="", name="ix")
    r = torznab.search(ix, "The Matrix 1999", mode="movie", year=1999, imdb_id="tt0133093")
    assert [x.title for x in r] == ["Hit"]
    assert calls[0]["imdbid"] == "0133093" and "q" not in calls[0]
    assert calls[1]["q"] == "The Matrix 1999" and "imdbid" not in calls[1]


def test_add_and_search_now(tmp_path, monkeypatch):
    from app.providers import tmdb

    dl = tmp_path / "dl"
    dl.mkdir()
    monkeypatch.setattr(settings, "downloads_dir", dl)
    factory.set_engine(FakeEngine(dl))
    monkeypatch.setattr(tmdb, "search_movies", lambda q, y=None, lang="en-US": [
        {"tmdb_id": 4242, "title": "Brand New", "year": 2024, "overview": "", "poster_url": None}])
    monkeypatch.setattr(tmdb, "movie_details", lambda i: {
        "tmdb_id": i, "title": "Brand New", "year": 2024, "overview": "", "poster_url": None,
        "certification": "15", "genres": [], "imdb_id": "tt0000042"})
    seen = {}

    def fake_search(db, query, mode="search", season=None, episode=None, year=None, categories="", **kw):
        seen.update(kw)
        return [Result("Brand.New.2024.1080p.WEB-DL.x264-G", "ix", "magnet:?xt=urn:btih:" + "c" * 40, "c" * 40, 3_000_000_000, 20)], []
    monkeypatch.setattr("app.indexers.manager.search_all", fake_search)

    with TestClient(app) as c:
        with SessionLocal() as db:
            db.query(Movie).filter_by(tmdb_id=4242).delete()
            if not db.query(RootFolder).filter_by(kind="movies_adults").first():
                db.add(RootFolder(path=str(tmp_path / "adults"), kind="movies_adults"))
            db.commit()
        assert c.get("/api/v1/movies/lookup?q=brand").json()[0]["in_library"] is False
        r = c.post("/api/v1/movies", json={"tmdb_id": 4242, "search_now": True}).json()
        assert r["grabbed"] == "Brand.New.2024.1080p.WEB-DL.x264-G"
        assert seen["imdb_id"] == "tt0000042"          # ID-based search used
        assert c.get("/api/v1/movies/lookup?q=brand").json()[0]["in_library"] is True
        assert c.post("/api/v1/movies", json={"tmdb_id": 4242}).status_code == 409
    factory.set_engine(None)


def test_rar_release_is_unpacked_and_imported(tmp_path, monkeypatch):
    import pytest

    from app.services import unpack
    from tests.rarfile_fixture import write_rar

    if not unpack.extractor():
        pytest.skip("no 7z/unrar installed")
    dl = tmp_path / "dl"
    rel = dl / "Packed.Movie.2012.1080p.BluRay.x264-G"
    rel.mkdir(parents=True)
    write_rar(rel / "pm.rar", "Packed.Movie.2012.1080p.BluRay.x264-G.mkv", b"VIDEO-BYTES" * 1000)
    (rel / "pm.nfo").write_text("info")
    monkeypatch.setattr(settings, "downloads_dir", dl)
    eng = FakeEngine(dl)
    eng.done = True
    eng.list = lambda: [TorrentStatus("a" * 40, "x", 1.0, "seeding", str(rel))]
    factory.set_engine(eng)
    with TestClient(app) as c, SessionLocal() as db:
        from app.models import QueueItem
        db.query(QueueItem).delete()
        root = RootFolder(path=str(tmp_path / "m"), kind="movies_adults")
        db.add(root)
        db.flush()
        mv = Movie(tmdb_id=9123, title="Packed Movie", year=2012, root_folder_id=root.id,
                   path=str(tmp_path / "m" / "Packed Movie (2012)"))
        db.add(mv)
        db.commit()
        from app.indexers.torznab import Result
        from app.services import grab

        grab.grab(db, Result("Packed.Movie.2012.1080p.BluRay.x264-G", "m", "magnet:x", "a" * 40), "movie", movie=mv)
        assert c.post("/api/v1/commands/sync-queue").json()["imported"] == 1
        out = tmp_path / "m" / "Packed Movie (2012)" / "Packed Movie (2012).mkv"
        assert out.read_bytes() == b"VIDEO-BYTES" * 1000
        assert (rel / "pm.rar").exists()                      # original archive kept for seeding
        assert not (dl / ".arr-unpack").exists() or not any((dl / ".arr-unpack").iterdir())
        assert "unpacked from archive" in c.get("/api/v1/history").json()[0]["detail"]
    factory.set_engine(None)


def test_queue_live_stats_and_pause(tmp_path, monkeypatch):
    dl = tmp_path / "dl"
    dl.mkdir()
    monkeypatch.setattr(settings, "downloads_dir", dl)
    paused = []
    eng = FakeEngine(dl)
    eng.list = lambda: [TorrentStatus("e" * 40, "x", 1.0, "seeding", str(dl), ratio=0.42, seeding_seconds=7200,
                                      uploaded=123_000_000, downloaded=300_000_000, upload_rate=50_000, peers=3,
                                      size=300_000_000)]
    eng.pause = lambda h: paused.append(("pause", h))
    eng.resume = lambda h: paused.append(("resume", h))
    factory.set_engine(eng)
    with TestClient(app) as c, SessionLocal() as db:
        from app.models import QueueItem
        db.query(QueueItem).delete()
        db.add(QueueItem(title="Seeding.Thing", info_hash="e" * 40, kind="movie", status="seeding", progress=1.0))
        db.commit()
        row = c.get("/api/v1/queue").json()[0]
        assert row["live"]["uploaded"] == 123_000_000 and row["live"]["ratio"] == 0.42
        assert row["live"]["seeding_seconds"] == 7200 and row["rules"]["ratio"] == 1.0
        qid = row["id"]
        assert c.post(f"/api/v1/queue/{qid}/pause").status_code == 200
        assert c.post(f"/api/v1/queue/{qid}/resume").status_code == 200
        assert paused == [("pause", "e" * 40), ("resume", "e" * 40)]
        assert c.post("/api/v1/queue/9999/pause").status_code == 404
    factory.set_engine(None)


def test_subtitles_copied_with_movie(tmp_path, monkeypatch):
    dl = tmp_path / "dl"
    rel = dl / "Sub.Movie.2015.1080p.BluRay.x264-G"
    (rel / "Subs").mkdir(parents=True)
    (rel / "Sub.Movie.2015.1080p.BluRay.x264-G.mkv").write_text("video")
    (rel / "Subs" / "2_English.srt").write_text("en")
    (rel / "Subs" / "Swedish.srt").write_text("sv")
    (rel / "Subs" / "3_Swedish_forced.srt").write_text("sv2")
    monkeypatch.setattr(settings, "downloads_dir", dl)
    eng = FakeEngine(dl)
    eng.done = True
    eng.list = lambda: [TorrentStatus("a" * 40, "x", 1.0, "seeding", str(rel))]
    factory.set_engine(eng)
    with TestClient(app) as c, SessionLocal() as db:
        from app.models import QueueItem
        from app.indexers.torznab import Result
        from app.services import grab
        db.query(QueueItem).delete()
        root = RootFolder(path=str(tmp_path / "m"), kind="movies_adults")
        db.add(root)
        db.flush()
        mv = Movie(tmdb_id=9555, title="Sub Movie", year=2015, root_folder_id=root.id, path=str(tmp_path / "m" / "Sub Movie (2015)"))
        db.add(mv)
        db.commit()
        grab.grab(db, Result("Sub.Movie.2015.1080p.BluRay.x264-G", "m", "magnet:x", "a" * 40), "movie", movie=mv)
        assert c.post("/api/v1/commands/sync-queue").json()["imported"] == 1
        folder = tmp_path / "m" / "Sub Movie (2015)"
        assert sorted(p.name for p in folder.iterdir()) == [
            "Sub Movie (2015).en.srt", "Sub Movie (2015).mkv", "Sub Movie (2015).sv.2.srt", "Sub Movie (2015).sv.srt"]
        assert "3 subtitle file(s)" in c.get("/api/v1/history").json()[0]["detail"]
    factory.set_engine(None)


def test_stalled_download_is_failed_and_blocklisted(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    from app.models import Blocklist, QueueItem

    dl = tmp_path / "dl"
    dl.mkdir()
    monkeypatch.setattr(settings, "downloads_dir", dl)
    removed = []
    eng = FakeEngine(dl)
    eng.list = lambda: [TorrentStatus("a" * 40, "x", 0.2, "downloading", str(dl))]
    eng.remove = lambda h, delete_files=False: removed.append((h, delete_files))
    factory.set_engine(eng)
    with TestClient(app) as c, SessionLocal() as db:
        db.query(QueueItem).delete()
        db.add(QueueItem(title="Stuck.Release.2020.1080p", info_hash="a" * 40, kind="movie", status="downloading",
                         progress=0.2, progress_changed_at=datetime.utcnow() - timedelta(hours=7)))
        db.commit()
        assert c.post("/api/v1/commands/sync-queue").json()["failed"] == 1
        item = db.query(QueueItem).first()
        db.refresh(item)
        assert item.status == "failed" and "stalled" in item.error
        assert removed == [("a" * 40, True)]
        assert db.query(Blocklist).filter_by(title="Stuck.Release.2020.1080p").count() == 1
        # progress made recently -> not stalled
        item.status, item.progress_changed_at = "downloading", datetime.utcnow() - timedelta(hours=1)
        db.commit()
        assert c.post("/api/v1/commands/sync-queue").json()["failed"] == 0
    factory.set_engine(None)


def test_low_disk_space_blocks_grab(tmp_path, monkeypatch):
    import shutil
    from collections import namedtuple

    from app.services import grab as grab_service
    from app.services.errors import LowDiskSpace

    dl = tmp_path / "dl"
    dl.mkdir()
    monkeypatch.setattr(settings, "downloads_dir", dl)
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(1000e9, 995e9, 5e9))
    with TestClient(app), SessionLocal() as db:
        from app.models import Setting
        import json
        db.merge(Setting(key="downloads", value=json.dumps({"stall_hours": 6, "min_free_gb": 20})))
        db.commit()
        try:
            grab_service.check_disk(db)
            raise AssertionError("expected LowDiskSpace")
        except LowDiskSpace as e:
            assert "5.0 GB free" in str(e)
        db.merge(Setting(key="downloads", value=json.dumps({"stall_hours": 6, "min_free_gb": 0})))
        db.commit()
        grab_service.check_disk(db)  # disabled -> fine


def test_choose_destination_when_adding(tmp_path, monkeypatch):
    from app.providers import tmdb

    monkeypatch.setattr(tmdb, "movie_details", lambda i: {
        "tmdb_id": i, "title": "Pick Me", "year": 2024, "overview": "", "poster_url": None,
        "certification": "R", "genres": [], "imdb_id": None, "release_date": None})   # rule would say: adults
    with TestClient(app) as c, SessionLocal() as db:
        db.query(Movie).filter(Movie.tmdb_id.in_([6001, 6002, 6003])).delete()
        db.query(RootFolder).delete()
        kids = RootFolder(path=str(tmp_path / "Barn"), kind="movies_kids")
        adults = RootFolder(path=str(tmp_path / "Vuxna"), kind="movies_adults")
        tv = RootFolder(path=str(tmp_path / "Serier"), kind="tv")
        db.add_all([kids, adults, tv])
        db.commit()
        ids = (kids.id, adults.id, tv.id)

        auto = c.post("/api/v1/movies", json={"tmdb_id": 6001}).json()
        assert auto["root_kind"] == "movies_adults"                                    # rule decides when nothing is chosen
        chosen = c.post("/api/v1/movies", json={"tmdb_id": 6002, "root_folder_id": ids[0]}).json()
        assert chosen["root_kind"] == "movies_kids" and chosen["path"].startswith(str(tmp_path / "Barn"))
        assert c.post("/api/v1/movies", json={"tmdb_id": 6003, "root_folder_id": ids[2]}).status_code == 400   # a TV folder
        assert c.post("/api/v1/movies", json={"tmdb_id": 6003, "root_folder_id": 99999}).status_code == 400


def test_seeding_totals_survive_engine_restart(tmp_path, monkeypatch):
    from datetime import datetime

    from app.models import QueueItem

    dl = tmp_path / "dl"
    dl.mkdir()
    monkeypatch.setattr(settings, "downloads_dir", dl)
    removed = []
    state = {"up": 400_000_000, "secs": 40 * 3600}
    eng = FakeEngine(dl)
    eng.list = lambda: [TorrentStatus("a" * 40, "x", 1.0, "seeding", str(dl), uploaded=state["up"],
                                      seeding_seconds=state["secs"], size=1_000_000_000)]
    eng.remove = lambda h, delete_files=False: removed.append(h)
    factory.set_engine(eng)
    with TestClient(app) as c, SessionLocal() as db:
        db.query(QueueItem).delete()
        db.add(QueueItem(title="Long.Seed", info_hash="a" * 40, kind="movie", status="seeding", progress=1.0,
                         imported_at=datetime.utcnow()))
        db.commit()
        c.post("/api/v1/commands/sync-queue")
        assert removed == []                                  # 0.4 ratio, 40 h: rule (ratio 1 / 72 h) not met
        state["up"], state["secs"] = 100_000_000, 3 * 3600     # container restarted: engine counters start again
        c.post("/api/v1/commands/sync-queue")
        live = c.get("/api/v1/queue").json()[0]["live"]
        assert live["uploaded"] == 500_000_000 and live["seeding_seconds"] == 43 * 3600
        state["up"], state["secs"] = 600_000_000, 30 * 3600    # +30 h later: 43 + 27 more... total passes 72 h
        c.post("/api/v1/commands/sync-queue")
        assert removed == ["a" * 40]                           # ratio 1.0 reached through the accumulated total
    factory.set_engine(None)


def test_change_movie_destination_only_when_not_on_disk(tmp_path):
    with TestClient(app) as c, SessionLocal() as db:
        db.query(Movie).filter(Movie.tmdb_id.in_([6201, 6202])).delete()
        db.query(RootFolder).delete()
        kids = RootFolder(path=str(tmp_path / "Barn"), kind="movies_kids")
        adults = RootFolder(path=str(tmp_path / "Vuxna"), kind="movies_adults")
        tv = RootFolder(path=str(tmp_path / "Serier"), kind="tv")
        db.add_all([kids, adults, tv])
        db.flush()
        wanted = Movie(tmdb_id=6201, title="Not Yet", year=2023, root_folder_id=adults.id, path=str(tmp_path / "Vuxna" / "Not Yet (2023)"))
        have = Movie(tmdb_id=6202, title="Have It", year=2020, root_folder_id=adults.id, has_file=True, path=str(tmp_path / "Vuxna" / "Have It (2020)"))
        db.add_all([wanted, have])
        db.commit()
        ids = (wanted.id, have.id, kids.id, tv.id)
        r = c.patch(f"/api/v1/movies/{ids[0]}", json={"root_folder_id": ids[2]}).json()
        assert r["root_kind"] == "movies_kids" and r["path"] == str(tmp_path / "Barn" / "Not Yet (2023)")
        assert c.patch(f"/api/v1/movies/{ids[1]}", json={"root_folder_id": ids[2]}).status_code == 400   # on disk
        assert c.patch(f"/api/v1/movies/{ids[0]}", json={"root_folder_id": ids[3]}).status_code == 400   # TV folder


def test_daily_show_episode_is_imported_by_date(tmp_path, monkeypatch):
    from datetime import date

    dl = tmp_path / "dl"
    rel = dl / "The.Daily.Show.2026.11.10.Guest.720p.WEB.h264-GRP"
    rel.mkdir(parents=True)
    (rel / "the.daily.show.2026.11.10.mkv").write_text("talk")
    monkeypatch.setattr(settings, "downloads_dir", dl)
    eng = FakeEngine(dl)
    eng.done = True
    eng.list = lambda: [TorrentStatus("a" * 40, "x", 1.0, "seeding", str(rel))]
    factory.set_engine(eng)
    with TestClient(app) as c, SessionLocal() as db:
        from app.models import QueueItem
        db.query(QueueItem).delete()
        s = Series(tvmaze_id=880011, title="The Daily Show", year=1996, path=str(tmp_path / "tv" / "The Daily Show (1996)"))
        s.episodes += [Episode(season=2026, number=45, title="Guest", air_date=date(2026, 11, 10)),
                       Episode(season=2026, number=46, title="Next", air_date=date(2026, 11, 11))]
        db.add(s)
        db.commit()
        e1 = [e for e in s.episodes if e.number == 45][0]
        from app.indexers.torznab import Result
        from app.services import grab
        grab.grab(db, Result(rel.name, "m", "magnet:x", "a" * 40), "episode", series=s, episodes=[e1])
        assert c.post("/api/v1/commands/sync-queue").json()["imported"] == 1
        db.expire_all()
        got = {e.number: e.has_file for e in db.get(Series, s.id).episodes}
        assert got == {45: True, 46: False}
    factory.set_engine(None)
