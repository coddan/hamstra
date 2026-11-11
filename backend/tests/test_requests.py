from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Movie, Request, User
from app.providers import tmdb
from app.services import auth
from tests.test_users import clean


def login(c, name, pw):
    assert c.post("/api/v1/auth/login", json={"username": name, "password": pw}).status_code == 200


def test_roles_and_requests(monkeypatch):
    clean()
    monkeypatch.setattr(tmdb, "movie_details", lambda i: {"tmdb_id": i, "title": "Wanted Film", "year": 2024, "overview": "",
                        "poster_url": None, "certification": "PG", "genres": [], "imdb_id": "tt9"})
    with SessionLocal() as db:
        db.query(Request).delete()
        db.query(Movie).filter_by(tmdb_id=5150).delete()
        db.commit()
    with TestClient(app) as admin:
        admin.post("/api/v1/auth/setup", json={"username": "boss", "password": "bosspassword"})
        admin.post("/api/v1/users", json={"username": "kid", "password": "kidpassword", "is_admin": False})
        kid = TestClient(app)
        login(kid, "kid", "kidpassword")

        # a normal user can browse and request ...
        assert kid.get("/api/v1/movies").status_code == 200
        assert kid.get("/api/v1/queue").status_code == 200
        # ... but cannot change anything else
        for method, path in [("get", "/api/v1/settings/plex"), ("get", "/api/v1/indexers"), ("get", "/api/v1/users"),
                             ("get", "/api/v1/system/logs"), ("post", "/api/v1/commands/search-wanted"),
                             ("post", "/api/v1/movies/1/search"), ("delete", "/api/v1/movies/1"),
                             ("post", "/api/v1/others/magnet"), ("post", "/api/v1/library/scan"),
                             ("get", "/api/v1/movies/1/releases"), ("get", "/api/v1/series/1/seasons/1/releases")]:
            assert getattr(kid, method)(path).status_code == 403, path

        body = {"kind": "movie", "external_id": 5150, "title": "Wanted Film", "year": 2024}
        r = kid.post("/api/v1/requests", json=body)
        assert r.status_code == 201 and r.json()["status"] == "pending" and r.json()["user"] == "kid"
        assert kid.post("/api/v1/requests", json=body).status_code == 409           # duplicate
        assert len(kid.get("/api/v1/requests").json()) == 1
        rid = r.json()["id"]
        assert kid.post(f"/api/v1/requests/{rid}/approve", json={}).status_code == 403   # cannot self-approve

        # admin sees it and approves: the movie is added
        assert [x["title"] for x in admin.get("/api/v1/requests").json()] == ["Wanted Film"]
        ok = admin.post(f"/api/v1/requests/{rid}/approve", json={"search_now": False})
        assert ok.status_code == 200 and ok.json()["status"] == "approved"
        assert any(m["title"] == "Wanted Film" for m in admin.get("/api/v1/movies").json())
        assert kid.post("/api/v1/requests", json=body).status_code == 409           # now in the library

        # deny + withdraw rules
        b2 = {"kind": "series", "external_id": 31337, "title": "Some Show", "year": 2020}
        r2 = kid.post("/api/v1/requests", json=b2).json()["id"]
        assert admin.post(f"/api/v1/requests/{r2}/deny", json={"note": "not now"}).json()["status"] == "denied"
        assert kid.get("/api/v1/requests").json()[0]["note"] == "not now"
        r3 = kid.post("/api/v1/requests", json={**b2, "external_id": 31338}).json()["id"]
        assert kid.delete(f"/api/v1/requests/{r3}").status_code == 204              # withdraw own pending
        assert kid.delete(f"/api/v1/requests/{r2}").status_code == 403              # not a pending one
    clean()
