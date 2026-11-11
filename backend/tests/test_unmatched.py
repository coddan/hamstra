from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Movie, RootFolder, Setting
from app.providers import tmdb


def test_unmatched_match_ignore(tmp_path, monkeypatch):
    base = tmp_path / "adults"
    (base / "Weird Name 2001 SWEDISH").mkdir(parents=True)
    (base / "Weird Name 2001 SWEDISH" / "x.mkv").write_text("v")
    (base / "Junk").mkdir()
    monkeypatch.setattr(tmdb, "movie_details", lambda i: {"tmdb_id": i, "title": "Real Title", "year": 2001, "overview": "",
                        "poster_url": None, "certification": "15", "genres": [], "imdb_id": "tt1"})
    with TestClient(app) as c:
        with SessionLocal() as db:
            db.query(Movie).delete()
            db.query(RootFolder).delete()
            db.merge(Setting(key="ignored_paths", value="[]"))
            db.add(RootFolder(path=str(base), kind="movies_adults"))
            db.commit()
        un = c.get("/api/v1/library/unmatched").json()
        assert {i["name"] for i in un["items"]} == {"Weird Name 2001 SWEDISH", "Junk"}
        weird = [i for i in un["items"] if i["name"].startswith("Weird")][0]
        assert weird["title"] == "Weird Name" and weird["year"] == 2001

        r = c.post("/api/v1/library/match", json={"path": weird["path"], "kind": "movie", "tmdb_id": 77})
        assert r.status_code == 201
        m = c.get("/api/v1/movies").json()[0]
        assert m["title"] == "Real Title" and m["has_file"] is True and m["path"] == weird["path"]
        # the same film again from another folder: refused, with the existing location named
        dup = c.post("/api/v1/library/match", json={"path": str(base / "Junk"), "kind": "movie", "tmdb_id": 77})
        assert dup.status_code == 409 and "Already in the library" in dup.json()["detail"]

        assert c.post("/api/v1/library/ignore", json={"path": str(base / "Junk")}).json()["ignored"] == 1
        assert c.get("/api/v1/library/unmatched").json()["items"] == []
        c.post("/api/v1/library/unignore", json={"path": str(base / "Junk")})
        assert [i["name"] for i in c.get("/api/v1/library/unmatched").json()["items"]] == ["Junk"]
        assert c.post("/api/v1/library/match", json={"path": "/nope/x", "kind": "movie", "tmdb_id": 5}).status_code == 400
