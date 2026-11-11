from datetime import date

from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.engines import factory
from app.engines.base import TorrentStatus
from app.indexers.torznab import Result
from app.main import app
from app.models import Episode, QueueItem, Series
from app.providers import tvmaze
from app.services import decision, grab, refresh
from app.services.parser import parse

from .test_e2e import FakeEngine


def test_tvmaze_specials_become_season_zero(monkeypatch):
    raw = [{"id": 1, "season": 1, "number": 1, "name": "Pilot", "airdate": "2020-01-01"},
           {"id": 9, "season": 1, "number": None, "name": "Later special", "airdate": "2020-06-01"},
           {"id": 5, "season": 1, "number": None, "name": "Early special", "airdate": "2020-02-01"}]
    monkeypatch.setattr(tvmaze, "_get", lambda path, **p: raw)
    eps = tvmaze.episodes(1)
    assert [(e["season"], e["number"], e["title"]) for e in eps] == [(1, 1, "Pilot"), (0, 1, "Early special"), (0, 2, "Later special")]


def test_special_numbers_stay_stable_and_are_not_monitored():
    s = Series(tvmaze_id=1, title="X", monitored=True)
    first = [{"season": 1, "number": 1, "title": "P", "air_date": "2020-01-01"},
             {"season": 0, "number": 1, "title": "B", "air_date": "2020-06-01"}]
    refresh.merge_episodes(s, first)
    # TVmaze now lists a special that aired earlier, so it comes first in its numbering
    second = [first[0], {"season": 0, "number": 1, "title": "A", "air_date": "2020-02-01"},
              {"season": 0, "number": 2, "title": "B", "air_date": "2020-06-01"}]
    added, _ = refresh.merge_episodes(s, second)
    sp = {e.title: (e.number, e.monitored) for e in s.episodes if e.season == 0}
    assert added == 1 and sp == {"B": (1, False), "A": (2, False)}
    assert [e.monitored for e in s.episodes if e.season == 1] == [True]


def test_parse_absolute_numbers():
    r = parse("[SubsPlease] Frieren - 12 (1080p) [ABC123].mkv")
    assert (r.title, r.absolute, r.season, r.resolution) == ("Frieren", 12, None, 1080)
    assert parse("One.Piece.-.1100.1080p.WEB.x264-GRP").absolute == 1100
    assert parse("Show - 2019 1080p").absolute is None           # a year
    assert parse("Show - 01-26 1080p batch").absolute is None    # a batch
    assert parse("Show.S02E03.1080p").absolute is None


def test_decision_absolute_needs_the_flag_and_the_right_number():
    prof = decision.Profile()
    r = Result("[Grp] Frieren - 12 [1080p]", "i", "u", "a" * 40, seeders=5, size=500_000_000)
    ok = decision.evaluate(r, decision.Want("episode", "Frieren", None, 1, 12, absolute=12), prof)
    assert ok.accepted
    assert "wrong episode" in decision.evaluate(r, decision.Want("episode", "Frieren", None, 1, 13, absolute=13), prof).reasons
    off = decision.evaluate(r, decision.Want("episode", "Frieren", None, 1, 12), prof)
    assert not off.accepted and "absolute" in off.reasons[0]
    assert "not a TV release" in decision.evaluate(Result("Frieren 1080p", "i", "u", "b" * 40, seeders=5), decision.Want("episode", "Frieren", None, 1, 1), prof).reasons


def test_absolute_numbers_skip_specials():
    s = Series(tvmaze_id=2, title="A")
    s.episodes += [Episode(season=0, number=1), Episode(season=1, number=1), Episode(season=1, number=2), Episode(season=2, number=1)]
    assert refresh.absolute_numbers(s) == {(1, 1): 1, (1, 2): 2, (2, 1): 3}


def test_candidates_search_by_date_and_by_absolute_number(monkeypatch):
    calls = []

    def fake(db, query, mode="search", **kw):
        calls.append((query, mode))
        return [Result(f"hit {len(calls)}", "i", f"u{len(calls)}", None)], []

    monkeypatch.setattr("app.indexers.manager.search_all", fake)
    monkeypatch.setattr(grab, "_ensure_ids", lambda *a: None)
    s = Series(tvmaze_id=3, title="Talk", absolute_numbering=True)
    s.episodes += [Episode(season=2026, number=1, air_date=date(2026, 11, 10)), Episode(season=2026, number=2)]
    out, _ = grab.candidates_episode(None, s, s.episodes[0])
    assert [c[0] for c in calls] == ["Talk", "Talk 2026 11 10", "Talk 01"] and len(out) == 3
    s.absolute_numbering = False
    calls.clear()
    grab.candidates_episode(None, s, s.episodes[0])
    assert [c[0] for c in calls] == ["Talk", "Talk 2026 11 10"]


def test_import_absolute_named_file(tmp_path, monkeypatch):
    dl = tmp_path / "dl"
    rel = dl / "rel"
    rel.mkdir(parents=True)
    (rel / "[Grp] Anime Show - 03 [1080p].mkv").write_text("x")
    monkeypatch.setattr(settings, "downloads_dir", dl)
    eng = FakeEngine(dl)
    eng.list = lambda: [TorrentStatus("a" * 40, "x", 1.0, "seeding", str(rel))]
    factory.set_engine(eng)
    with TestClient(app) as c, SessionLocal() as db:
        db.query(QueueItem).delete()
        s = Series(tvmaze_id=880022, title="Anime Show", year=2023, absolute_numbering=True, path=str(tmp_path / "tv" / "Anime Show (2023)"))
        s.episodes += [Episode(season=1, number=1), Episode(season=1, number=2), Episode(season=2, number=1, title="Third")]
        db.add(s)
        db.commit()
        e3 = [e for e in s.episodes if e.season == 2][0]
        grab.grab(db, Result("[Grp] Anime Show - 03 [1080p]", "m", "magnet:x", "a" * 40), "episode", series=s, episodes=[e3])
        assert c.post("/api/v1/commands/sync-queue").json()["imported"] == 1
        db.expire_all()
        got = {(e.season, e.number): bool(e.file_path) for e in db.get(Series, s.id).episodes}
        assert got == {(1, 1): False, (1, 2): False, (2, 1): True}
        assert db.get(Series, s.id).episodes[2].file_path.endswith("Season 02/Anime Show - S02E01 - Third.mkv")
    factory.set_engine(None)
