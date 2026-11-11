from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.engines import factory
from app.indexers.torznab import Result
from app.main import app
import json

from app.models import Episode, Movie, QueueItem, Series, Setting
from tests.test_e2e import FakeEngine


def test_rss_matches_new_releases(tmp_path, monkeypatch):
    dl = tmp_path / "dl"
    dl.mkdir()
    monkeypatch.setattr(settings, "downloads_dir", dl)
    factory.set_engine(FakeEngine(dl))
    feed = [
        Result("Wanted.Movie.2024.1080p.WEB-DL.x264-G", "ix", "magnet:?xt=urn:btih:" + "1" * 40, "1" * 40, 3_000_000_000, 30),
        Result("Wanted.Movie.2024.CAM.x264-G", "ix", "magnet:?xt=urn:btih:" + "2" * 40, "2" * 40, 1_000_000_000, 90),
        Result("Other.Movie.2020.1080p.WEB-DL.x264-G", "ix", "magnet:x", "3" * 40, 3_000_000_000, 30),
        Result("Wanted.Show.S02E05.1080p.WEB-DL.x264-G", "ix", "magnet:?xt=urn:btih:" + "4" * 40, "4" * 40, 900_000_000, 30),
        Result("Wanted.Show.S02E06.1080p.WEB-DL.x264-G", "ix", "magnet:?xt=urn:btih:" + "5" * 40, "5" * 40, 900_000_000, 30),  # not aired yet
        Result("Wanted.Show.S02.1080p.WEB-DL.x264-G", "ix", "magnet:x", "6" * 40, 9_000_000_000, 30),  # pack: ignored by rss
    ]
    monkeypatch.setattr("app.indexers.manager.search_all", lambda db, q, mode="search", **kw: (feed, []))
    with TestClient(app) as c, SessionLocal() as db:
        db.merge(Setting(key="automation", value=json.dumps({"enabled": True, "dry_run": False, "rss": True, "search": True})))
        db.query(QueueItem).delete(); db.query(Episode).delete(); db.query(Series).delete(); db.query(Movie).delete()
        db.add(Movie(tmdb_id=701, title="Wanted Movie", year=2024, monitored=True))
        db.add(Movie(tmdb_id=702, title="Unmonitored Movie", year=2024, monitored=False))
        s = Series(tvmaze_id=801, title="Wanted Show", year=2022, monitored=True)
        s.episodes += [Episode(season=2, number=5, air_date=date.today() - timedelta(days=1)),
                       Episode(season=2, number=6, air_date=date.today() + timedelta(days=6))]
        db.add(s)
        db.commit()
        r = c.post("/api/v1/commands/rss-sync").json()
        assert r["releases"] == 6 and r["grabbed"] == 2
        titles = sorted(i.title for i in db.query(QueueItem).all())
        assert titles == ["Wanted.Movie.2024.1080p.WEB-DL.x264-G", "Wanted.Show.S02E05.1080p.WEB-DL.x264-G"]
        assert c.post("/api/v1/commands/rss-sync").json()["grabbed"] == 0   # already queued
        db.merge(Setting(key="automation", value=json.dumps({"enabled": False, "dry_run": True, "rss": True, "search": True})))
        db.query(QueueItem).delete()
        db.commit()
    factory.set_engine(None)
