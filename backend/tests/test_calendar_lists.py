from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Movie, RootFolder
from app.providers import tmdb, tvmaze


def test_calendar_includes_upcoming_movies():
    with TestClient(app) as c, SessionLocal() as db:
        db.query(Movie).filter(Movie.tmdb_id.in_([8801, 8802])).delete()
        db.add_all([Movie(tmdb_id=8801, title="Soon Film", year=2026, release_date=date.today() + timedelta(days=5)),
                    Movie(tmdb_id=8802, title="Far Film", year=2027, release_date=date.today() + timedelta(days=400))])
        db.commit()
        cal = c.get("/api/v1/calendar").json()
        movies = [x for x in cal if x["type"] == "movie"]
        assert [m["title"] for m in movies] == ["Soon Film"]


def test_import_tmdb_list(monkeypatch, tmp_path):
    monkeypatch.setattr(tmdb, "list_items", lambda lid: [
        {"media_type": "movie", "id": 9001, "title": "List Movie", "year": 2020},
        {"media_type": "movie", "id": 9002, "title": "Have Already", "year": 2021},
        {"media_type": "tv", "id": 55, "title": "List Show", "year": 2019},
        {"media_type": "tv", "id": 56, "title": "Lost Show", "year": 2018}])
    monkeypatch.setattr(tmdb, "movie_details", lambda i: {"tmdb_id": i, "title": f"Film {i}", "year": 2020, "overview": "",
                        "poster_url": None, "certification": "PG", "genres": [], "imdb_id": None, "release_date": "2020-05-01"})
    monkeypatch.setattr(tmdb, "tv_imdb_id", lambda i: "tt55" if i == 55 else None)
    monkeypatch.setattr(tvmaze, "lookup_imdb", lambda imdb: [{"tvmaze_id": 7700, "title": "List Show"}])
    monkeypatch.setattr(tvmaze, "show_details", lambda i: {"tvmaze_id": i, "title": "List Show", "year": 2019, "overview": "",
                        "poster_url": None, "status": "Running", "imdb_id": "tt55", "tvdb_id": 5})
    monkeypatch.setattr(tvmaze, "episodes", lambda i: [{"season": 1, "number": 1, "title": "Pilot", "air_date": "2019-01-01"}])
    with TestClient(app) as c, SessionLocal() as db:
        from app.models import Series
        db.query(Movie).filter(Movie.tmdb_id.in_([9001, 9002])).delete()
        db.query(Series).filter_by(tvmaze_id=7700).delete()
        for kind, path in (("movies_kids", str(tmp_path / "k")), ("movies_adults", str(tmp_path / "a")), ("tv", str(tmp_path / "t"))):
            if not db.query(RootFolder).filter_by(kind=kind).first():
                db.add(RootFolder(path=path, kind=kind))
        db.add(Movie(tmdb_id=9002, title="Have Already", year=2021))
        db.commit()
        r = c.post("/api/v1/library/import-list", json={"list": "https://www.themoviedb.org/list/8123456-my-list"}).json()
        assert r["added"] == ["List Movie (2020)", "List Show (2019)"]
        assert r["skipped"] == ["Have Already (2021)"]
        assert r["failed"][0]["item"] == "Lost Show (2018)"
        assert c.post("/api/v1/library/import-list", json={"list": "abc"}).status_code == 400
        added = [m for m in c.get("/api/v1/movies").json() if m["tmdb_id"] == 9001][0]
        assert added["has_file"] is False


def test_trakt_url_parsing_and_items(monkeypatch):
    from app.providers import trakt

    assert trakt.parse_url("https://trakt.tv/users/justin/lists/favourites?sort=rank") == "/users/justin/lists/favourites/items"
    assert trakt.parse_url("https://trakt.tv/movies/trending") == "/movies/trending"
    import pytest
    with pytest.raises(trakt.TraktError):
        trakt.parse_url("https://example.com/nope")
    with pytest.raises(trakt.TraktError):
        trakt.list_items("https://trakt.tv/movies/trending", "")           # no client id

    seen = {}

    def fake_get(url, params=None, timeout=None, follow_redirects=None, headers=None):
        seen.update(url=url, key=headers["trakt-api-key"])
        import httpx
        return httpx.Response(200, request=httpx.Request("GET", url), json=[
            {"type": "movie", "movie": {"title": "A Movie", "year": 2020, "ids": {"tmdb": 11, "imdb": "tt11"}}},
            {"type": "show", "show": {"title": "A Show", "year": 2019, "ids": {"tmdb": 22, "imdb": "tt22"}}},
            {"type": "season", "season": {}}])
    monkeypatch.setattr(trakt.httpx, "get", fake_get)
    items = trakt.list_items("https://trakt.tv/users/x/lists/y", "CID")
    assert [(i["type"], i["tmdb"], i["imdb"]) for i in items] == [("movie", 11, "tt11"), ("show", 22, "tt22")]
    assert seen["key"] == "CID" and seen["url"].endswith("/users/x/lists/y/items")


def test_import_trakt_list_through_the_api(monkeypatch, tmp_path):
    import json

    from app.db import SessionLocal
    from app.models import Series, Setting
    from app.providers import trakt, tmdb, tvmaze

    monkeypatch.setattr(trakt, "list_items", lambda url, cid: [
        {"type": "movie", "title": "Tmovie", "year": 2020, "tmdb": 9701, "imdb": "tt1"},
        {"type": "show", "title": "Tshow", "year": 2019, "tmdb": 1, "imdb": "tt2"}])
    monkeypatch.setattr(tmdb, "movie_details", lambda i: {"tmdb_id": i, "title": "Tmovie", "year": 2020, "overview": "", "poster_url": None,
                        "certification": "PG", "genres": [], "imdb_id": "tt1", "release_date": None})
    monkeypatch.setattr(tvmaze, "lookup_imdb", lambda imdb: [{"tvmaze_id": 7701, "title": "Tshow"}])
    monkeypatch.setattr(tvmaze, "show_details", lambda i: {"tvmaze_id": i, "title": "Tshow", "year": 2019, "overview": "", "poster_url": None,
                        "status": "Running", "imdb_id": "tt2", "tvdb_id": 3})
    monkeypatch.setattr(tvmaze, "episodes", lambda i: [])
    with TestClient(app) as c, SessionLocal() as db:
        db.query(Movie).filter_by(tmdb_id=9701).delete(); db.query(Series).filter_by(tvmaze_id=7701).delete()
        for kind, path in (("movies_adults", str(tmp_path / "a")), ("tv", str(tmp_path / "t"))):
            if not db.query(RootFolder).filter_by(kind=kind).first():
                db.add(RootFolder(path=path, kind=kind))
        db.commit()
        r = c.post("/api/v1/library/import-list", json={"list": "https://trakt.tv/users/x/lists/y"}).json()
        assert r["added"] == ["Tmovie (2020)", "Tshow (2019)"] and r["failed"] == []
        assert c.post("/api/v1/library/import-list", json={"list": "https://trakt.tv/users/x/lists/y"}).json()["skipped"] == ["Tmovie (2020)", "Tshow (2019)"]
        assert c.get("/api/v1/settings/trakt").json() == {"client_id": ""}                 # secrets are masked / empty by default


def test_calendar_range_and_flags():
    from datetime import date

    from app.models import Episode, Series

    with TestClient(app) as c, SessionLocal() as db:
        db.query(Series).filter_by(tvmaze_id=990011).delete()
        s = Series(tvmaze_id=990011, title="Cal Show", year=2026, monitored=False)
        s.episodes += [Episode(season=1, number=1, title="In", air_date=date(2031, 3, 10), monitored=False),
                       Episode(season=1, number=2, title="Out", air_date=date(2031, 5, 1))]
        db.add(s)
        db.commit()
        rows = c.get("/api/v1/calendar", params={"start": "2031-03-01", "end": "2031-03-31"}).json()
        assert [(r["series"], r["date"], r["monitored"], r["type"]) for r in rows] == [("Cal Show", "2031-03-10", False, "episode")]
        db.query(Episode).filter_by(series_id=s.id).delete()
        db.delete(db.get(Series, s.id))
        db.commit()
