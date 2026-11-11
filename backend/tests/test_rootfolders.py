from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Movie, RootFolder, Series, Setting
from app.providers import tmdb, tvmaze
from app.services import scan as scan_service


def reset(db):
    db.query(Movie).delete()
    for s in db.query(Series).all():
        db.delete(s)
    db.query(RootFolder).delete()
    for k in ("collection_folders", "ignored_paths"):
        db.merge(Setting(key=k, value="[]"))
    for k in ("guessed_matches", "duplicate_folders"):
        db.merge(Setting(key=k, value="{}"))
    db.commit()


def test_root_folder_crud(tmp_path):
    a, b = tmp_path / "films", tmp_path / "shows"
    a.mkdir(); b.mkdir()
    with TestClient(app) as c, SessionLocal() as db:
        reset(db)
        r = c.post("/api/v1/rootfolders", json={"path": str(a), "kind": "movies"}).json()
        assert r["label"] == "Movies" and r["exists"] is True and r["items"] == 0
        assert c.post("/api/v1/rootfolders", json={"path": str(a), "kind": "tv"}).status_code == 409       # same folder twice
        assert c.post("/api/v1/rootfolders", json={"path": str(a / "sub"), "kind": "tv"}).status_code == 400  # overlaps
        assert c.post("/api/v1/rootfolders", json={"path": "relative/path", "kind": "tv"}).status_code == 400
        assert c.post("/api/v1/rootfolders", json={"path": str(b), "kind": "nonsense"}).status_code == 400
        t = c.post("/api/v1/rootfolders", json={"path": str(b), "kind": "mixed"}).json()
        assert c.patch(f"/api/v1/rootfolders/{t['id']}", json={"path": str(b), "kind": "tv"}).json()["kind"] == "tv"
        listing = c.get("/api/v1/rootfolders").json()
        assert "mixed" in listing["kinds"] and [f["kind"] for f in listing["folders"]] == ["movies", "tv"]

        db.add(Movie(tmdb_id=777, title="X", year=2000, root_folder_id=r["id"], path=str(a / "X")))
        db.commit()
        assert c.patch(f"/api/v1/rootfolders/{r['id']}", json={"path": str(tmp_path / "other"), "kind": "movies"}).status_code == 400
        assert c.delete(f"/api/v1/rootfolders/{r['id']}").status_code == 409                               # in use
        assert c.delete(f"/api/v1/rootfolders/{r['id']}?detach=true").status_code == 204
        assert db.query(Movie).filter_by(tmdb_id=777).first() is not None                                 # the movie stays
        reset(db)


def test_movie_goes_to_a_generic_movie_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(tmdb, "movie_details", lambda i: {"tmdb_id": i, "title": "Any Film", "year": 2021, "overview": "",
                        "poster_url": None, "certification": "R", "genres": [], "imdb_id": None, "release_date": None})
    with TestClient(app) as c, SessionLocal() as db:
        reset(db)
        assert c.post("/api/v1/movies", json={"tmdb_id": 5001}).status_code == 400                         # no movie folder at all
        db.add(RootFolder(path=str(tmp_path / "films"), kind="movies"))
        db.commit()
        m = c.post("/api/v1/movies", json={"tmdb_id": 5001}).json()                                        # kids/adults rule has no such folders
        assert m["root_kind"] == "movies" and m["path"] == str(tmp_path / "films" / "Any Film (2021)")
        reset(db)


def test_mixed_folder_sorted_by_name_and_mismatch_flag(tmp_path):
    mixed, movies = tmp_path / "Everything", tmp_path / "Films"
    for d in (mixed / "Show.Name.S02.1080p", mixed / "Some Film (2010)", movies / "Other.Show.S01E01.720p", movies / "Plain Film (1999)"):
        d.mkdir(parents=True)
    with TestClient(app) as c, SessionLocal() as db:
        reset(db)
        db.add_all([RootFolder(path=str(mixed), kind="mixed"), RootFolder(path=str(movies), kind="movies")])
        db.commit()
        items = {i["name"]: i for i in c.get("/api/v1/library/unmatched").json()["items"]}
        assert items["Show.Name.S02.1080p"]["kind"] == "tv" and items["Show.Name.S02.1080p"]["mismatch"] is False   # mixed: by name
        assert items["Some Film (2010)"]["kind"] == "movie"
        assert items["Other.Show.S01E01.720p"]["mismatch"] is True        # an episode name inside a movies folder: flagged
        assert items["Plain Film (1999)"]["mismatch"] is False
        # the auto-matcher does not force a movie match onto the mismatch
        res = scan_service.import_unmatched(db)
        reasons = {f["path"].split("/")[-1]: f["reason"] for f in res["failed"]}
        assert "series but sits in a movies folder" in reasons["Other.Show.S01E01.720p"]
        reset(db)
