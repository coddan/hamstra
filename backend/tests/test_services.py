from app.services.naming import normalize, parse_episode, parse_folder
from app.services.rules import DEFAULTS, pick_movie_kind


def test_parse_episode():
    assert parse_episode("Show.S01E02.1080p.mkv") == [(1, 2)]
    assert parse_episode("Show.S01E02E03.mkv") == [(1, 2), (1, 3)]
    assert parse_episode("Show.S01E02-E04.mkv") == [(1, 2), (1, 3), (1, 4)]
    assert parse_episode("Show 2x05.mkv") == [(2, 5)]
    assert parse_episode("random.mkv") == []


def test_parse_folder_and_normalize():
    assert parse_folder("Shrek (2001)") == ("Shrek", 2001)
    assert parse_folder("Shrek") == ("Shrek", None)
    assert normalize("Amélie: The Movie!") == "amelie the movie"


def test_kids_rule():
    r = dict(DEFAULTS)
    assert pick_movie_kind(r, "PG", []) == "movies_kids"
    assert pick_movie_kind(r, "R", ["Family"]) == "movies_adults"
    assert pick_movie_kind(r, None, ["Animation"]) == "movies_kids"
    assert pick_movie_kind(r, None, ["Horror"]) == "movies_adults"
    r["kids_certifications"] = ["G"]
    assert pick_movie_kind(r, "PG", []) == "movies_adults"
    r["default_kind"] = "movies_kids"
    assert pick_movie_kind(r, None, []) == "movies_kids"


def test_imdb_id_in():
    from app.services.naming import imdb_id_in

    assert imdb_id_in("tt18224594") == "tt18224594"
    assert imdb_id_in("https://www.imdb.com/title/tt0133093/?ref_=x") == "tt0133093"
    assert imdb_id_in("Blade Runner 2099") is None


def test_plex_partial_scan(monkeypatch):
    from types import SimpleNamespace

    from app.db import SessionLocal
    from app.models import RootFolder, Setting
    from app.services import notify

    calls = []
    monkeypatch.setattr(notify, "plex_sections", lambda db: [
        {"id": "3", "title": "TV", "type": "show", "folders": ["/data/Serier"]},
        {"id": "2", "title": "Barn", "type": "movie", "folders": ["/data/film/Barn"]}])
    monkeypatch.setattr(notify.httpx, "get", lambda url, **kw: calls.append((url, kw.get("params"))) or SimpleNamespace(raise_for_status=lambda: None))
    from fastapi.testclient import TestClient
    from app.main import app
    import json
    with TestClient(app), SessionLocal() as db:
        db.query(RootFolder).delete()
        db.add_all([RootFolder(path="/mnt/media/Serier", kind="tv"), RootFolder(path="/mnt/media/film/Barn", kind="movies_kids")])
        db.merge(Setting(key="plex", value=json.dumps({"url": "http://plex:32400", "token": "t", "section_ids": []})))
        db.commit()
        assert notify.plex_refresh(db, "/mnt/media/Serier/Show (2020)") == "scanned 1 location(s)"
        assert calls[-1] == ("http://plex:32400/library/sections/3/refresh", {"path": "/data/Serier/Show (2020)"})
        notify.plex_refresh(db, "/mnt/media/film/Barn/Film (2010)")
        assert calls[-1][0].endswith("/sections/2/refresh") and calls[-1][1] == {"path": "/data/film/Barn/Film (2010)"}
        notify.plex_refresh(db, "/elsewhere/x")  # unknown path -> all sections
        assert len(calls) == 4
