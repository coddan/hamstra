import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.engines import factory
from app.indexers import manager
from app.indexers.torznab import Result
from app.main import app
from app.models import Episode, History, Movie, QueueItem, Series, Setting
from app.providers import tvmaze
from tests.test_e2e import FakeEngine


def test_series_refresh_adds_new_episodes(monkeypatch):
    eps = [{"season": 1, "number": n, "title": f"Ep{n}", "air_date": "2021-01-01"} for n in (1, 2)]
    monkeypatch.setattr(tvmaze, "show_details", lambda i: {"tvmaze_id": i, "title": "Run Show", "year": 2021, "overview": "o",
                        "poster_url": None, "status": "Running", "imdb_id": "tt1", "tvdb_id": 9})
    monkeypatch.setattr(tvmaze, "episodes", lambda i: eps)
    with TestClient(app) as c, SessionLocal() as db:
        db.query(Series).filter_by(tvmaze_id=777001).delete()
        s = Series(tvmaze_id=777001, title="Run Show", year=2021, monitored=True, status="Running")
        s.episodes.append(Episode(season=1, number=1, title="Old title", air_date=date(2021, 1, 1), monitored=True))
        db.add(s)
        db.commit()
        sid = s.id
        r = c.post(f"/api/v1/series/{sid}/refresh").json()
        assert r["added"] == 1 and r["changed"] == 1                     # episode 2 is new, episode 1 got a title
        eps.append({"season": 2, "number": 1, "title": "New season", "air_date": "2026-12-01"})
        assert c.post(f"/api/v1/series/{sid}/refresh").json()["added"] == 1
        db.expire_all()
        s = db.get(Series, sid)
        assert [e.monitored for e in s.episodes] == [True, True, True]   # follows the series flag
        assert s.refreshed_at is not None
        # an unmonitored series gets unmonitored new episodes
        s.monitored = False
        db.commit()
        eps.append({"season": 2, "number": 2, "title": "Later", "air_date": None})
        c.post(f"/api/v1/series/{sid}/refresh")
        db.expire_all()
        assert [e.monitored for e in db.get(Series, sid).episodes][-1] is False


def test_refresh_due_schedule():
    from app.services.refresh import due

    now = datetime.utcnow()
    running = SimpleNamespace(refreshed_at=now - timedelta(hours=7), status="Running")
    fresh = SimpleNamespace(refreshed_at=now - timedelta(hours=1), status="Running")
    ended = SimpleNamespace(refreshed_at=now - timedelta(days=2), status="Ended")
    old_ended = SimpleNamespace(refreshed_at=now - timedelta(days=8), status="Ended")
    never = SimpleNamespace(refreshed_at=None, status="Ended")
    assert [due(s, now) for s in (running, fresh, ended, old_ended, never)] == [True, False, False, True, True]


def test_pacing(monkeypatch):
    sleeps, clock = [], {"t": 100.0}
    monkeypatch.setattr(manager.time, "sleep", lambda s: sleeps.append(round(s, 2)) or clock.__setitem__("t", clock["t"] + s))
    monkeypatch.setattr(manager.time, "monotonic", lambda: clock["t"])
    ipt = SimpleNamespace(id=9101, kind="iptorrents")
    manager._last.pop(9101, None)
    manager.pace(ipt)
    assert sleeps == []                           # first request goes straight out
    clock["t"] += 1.0
    manager.pace(ipt)
    assert sleeps == [2.0]                        # 3 s minimum for IPTorrents, 1 s already passed


def test_dry_run_records_but_does_not_download(tmp_path, monkeypatch):
    dl = tmp_path / "dl"
    dl.mkdir()
    monkeypatch.setattr(settings, "downloads_dir", dl)
    added = []
    eng = FakeEngine(dl)
    eng.add = lambda url, path, cat="arr": added.append(url) or "a" * 40
    factory.set_engine(eng)
    feed = [Result("Dry.Movie.2024.1080p.WEB-DL.x264-G", "ix", "magnet:?xt=urn:btih:" + "1" * 40, "1" * 40, 3_000_000_000, 30)]
    monkeypatch.setattr("app.indexers.manager.search_all", lambda db, q, mode="search", **kw: (feed, []))
    with TestClient(app) as c, SessionLocal() as db:
        db.query(QueueItem).delete(); db.query(Movie).delete(); db.query(History).delete()
        db.add(Movie(tmdb_id=7001, title="Dry Movie", year=2024, monitored=True))
        db.merge(Setting(key="automation", value=json.dumps({"enabled": False, "dry_run": True, "rss": True, "search": True})))
        db.commit()

        r = c.post("/api/v1/commands/rss-sync").json()          # manual run honours dry-run
        assert r["dry_run"] is True and added == [] and db.query(QueueItem).count() == 0
        hist = c.get("/api/v1/history").json()
        assert hist[0]["event"] == "would_grab" and hist[0]["title"] == feed[0].title
        c.post("/api/v1/commands/rss-sync")
        assert len([h for h in c.get("/api/v1/history").json() if h["event"] == "would_grab"]) == 1   # not repeated

        db.merge(Setting(key="automation", value=json.dumps({"enabled": True, "dry_run": False, "rss": True, "search": True})))
        db.commit()
        c.post("/api/v1/commands/rss-sync")
        assert len(added) == 1 and db.query(QueueItem).count() == 1                  # real grab once dry-run is off

        from app.services import automation
        db.merge(Setting(key="automation", value=json.dumps({"enabled": False, "dry_run": False, "rss": True, "search": True})))
        db.commit()
        assert automation.run(db, "rss", lambda d: {"x": 1}) == {"disabled": True}   # scheduler does nothing when disabled
        db.query(QueueItem).delete(); db.query(Movie).delete(); db.query(History).delete()
        db.merge(Setting(key="automation", value=json.dumps({"enabled": False, "dry_run": True, "rss": True, "search": True})))
        db.commit()
    factory.set_engine(None)
