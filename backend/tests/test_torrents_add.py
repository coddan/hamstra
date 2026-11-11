from datetime import date

from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.engines import factory
from app.main import app
from app.models import Episode, Movie, QueueItem, RootFolder, Series
from app.providers import tmdb, tvmaze
from app.services.bencode import info_hash
from tests.test_e2e import FakeEngine
from tests.test_others import make_torrent


def setup_providers(monkeypatch):
    monkeypatch.setattr(tmdb, "search_movies_ext", lambda q, y=None, language="en-US": [
        {"tmdb_id": 603, "title": "The Matrix", "original_title": "The Matrix", "year": 1999, "overview": "", "poster_url": None},
        {"tmdb_id": 604, "title": "The Matrix Reloaded", "original_title": "The Matrix Reloaded", "year": 2003, "overview": "", "poster_url": None}]
        if q.lower().startswith("the matrix") else [])
    monkeypatch.setattr(tmdb, "movie_details", lambda i: {"tmdb_id": i, "title": "The Matrix", "year": 1999, "overview": "",
                        "poster_url": None, "certification": "15", "genres": [], "imdb_id": "tt0133093", "release_date": "1999-03-31"})
    monkeypatch.setattr(tvmaze, "search_shows", lambda q: [{"tvmaze_id": 4321, "title": "Show Name", "year": 2020,
                        "overview": "", "poster_url": None, "status": "Running"}] if "show name" in q.lower() else [])
    monkeypatch.setattr(tvmaze, "show_details", lambda i: {"tvmaze_id": i, "title": "Show Name", "year": 2020, "overview": "",
                        "poster_url": None, "status": "Running", "imdb_id": None, "tvdb_id": None})
    monkeypatch.setattr(tvmaze, "episodes", lambda i: [{"season": s, "number": n, "title": f"Ep{s}{n}", "air_date": "2021-01-01"}
                                                       for s in (1, 2) for n in range(1, 7)])


def test_movie_from_torrent_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "downloads_dir", tmp_path / "dl")
    (tmp_path / "dl").mkdir()
    factory.set_engine(FakeEngine(tmp_path / "dl"))
    setup_providers(monkeypatch)
    t = make_torrent("The.Matrix.1999.1080p.BluRay.x264-GRP")
    with TestClient(app) as c, SessionLocal() as db:
        db.query(QueueItem).delete(); db.query(Movie).filter_by(tmdb_id=603).delete()
        if not db.query(RootFolder).filter_by(kind="movies_adults").first():
            db.add(RootFolder(path=str(tmp_path / "adults"), kind="movies_adults"))
        if not db.query(RootFolder).filter_by(kind="movies_kids").first():
            db.add(RootFolder(path=str(tmp_path / "kids"), kind="movies_kids"))
        db.commit()
        files = {"file": ("m.torrent", t, "application/x-bittorrent")}
        r = c.post("/api/v1/torrents/inspect", files=files).json()
        assert r["kind"] == "movie" and r["title"] == "The Matrix" and r["year"] == 1999
        assert r["candidates"][0]["tmdb_id"] == 603 and r["candidates"][0]["in_library"] is False   # exact match ranks first

        a = c.post("/api/v1/torrents/add", files=files, data={"kind": "movie", "tmdb_id": "603"})
        assert a.status_code == 201 and a.json()["library_item"] == "The Matrix"
        assert db.query(Movie).filter_by(tmdb_id=603).count() == 1                   # added to the library on the way
        q = c.get("/api/v1/queue").json()[0]
        assert q["kind"] == "movie" and q["title"] == "The.Matrix.1999.1080p.BluRay.x264-GRP"
        assert c.post("/api/v1/torrents/inspect", files=files).json()["candidates"][0]["in_library"] is True
        assert c.post("/api/v1/torrents/add", files={"file": ("x", b"junk", "x")}, data={"kind": "movie", "tmdb_id": "603"}).status_code == 400
        assert c.post("/api/v1/torrents/add", files=files, data={"kind": "movie"}).status_code == 400   # no title picked
    factory.set_engine(None)


def test_series_episode_pack_and_magnet(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "downloads_dir", tmp_path / "dl")
    (tmp_path / "dl").mkdir()
    factory.set_engine(FakeEngine(tmp_path / "dl"))
    setup_providers(monkeypatch)
    with TestClient(app) as c, SessionLocal() as db:
        db.query(QueueItem).delete()
        db.query(Episode).delete(); db.query(Series).filter_by(tvmaze_id=4321).delete()
        if not db.query(RootFolder).filter_by(kind="tv").first():
            db.add(RootFolder(path=str(tmp_path / "tv"), kind="tv"))
        db.commit()

        ep = make_torrent("Show.Name.S02E03E04.1080p.WEB-DL.x264-G")
        r = c.post("/api/v1/torrents/inspect", files={"file": ("e.torrent", ep, "x")}).json()
        assert r["kind"] == "series" and r["season"] == 2 and r["episodes"] == [3, 4] and r["candidates"][0]["tvmaze_id"] == 4321
        a = c.post("/api/v1/torrents/add", files={"file": ("e.torrent", ep, "x")}, data={"kind": "series", "tvmaze_id": "4321"}).json()
        assert a["season"] == 2 and a["episodes"] == [3, 4]
        s = db.query(Series).filter_by(tvmaze_id=4321).first()
        assert s.monitored is False and not any(e.monitored for e in s.episodes)     # created unmonitored

        pack = make_torrent("Show.Name.S01.1080p.WEB-DL.x264-G")
        a = c.post("/api/v1/torrents/add", files={"file": ("p.torrent", pack, "x")}, data={"kind": "series", "tvmaze_id": "4321"}).json()
        assert a["season"] == 1 and a["episodes"] == [1, 2, 3, 4, 5, 6]               # whole season

        # a magnet without any season info needs the season to be chosen
        mag = "magnet:?xt=urn:btih:" + "ab" * 20 + "&dn=Show+Name+Something"
        assert c.post("/api/v1/torrents/add", data={"magnet": mag, "kind": "series", "tvmaze_id": "4321"}).status_code == 400
        ok = c.post("/api/v1/torrents/add", data={"magnet": mag, "kind": "series", "tvmaze_id": "4321", "season": "2"})
        assert ok.status_code == 201 and ok.json()["season"] == 2
        # nameless magnet: inspect explains, nothing to guess from
        nm = c.post("/api/v1/torrents/inspect", data={"magnet": "magnet:?xt=urn:btih:" + "cd" * 20}).json()
        assert nm["kind"] is None and "no name" in nm["note"]
        assert c.post("/api/v1/torrents/inspect", data={"magnet": "https://nope"}).status_code == 400
    factory.set_engine(None)
