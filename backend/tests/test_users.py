from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import User
from app.services import auth


def clean():
    from app.migrate import run_migrations
    run_migrations()
    with SessionLocal() as db:
        db.query(User).delete()
        db.commit()
    auth._fails.clear()


def test_setup_login_roles():
    clean()
    with TestClient(app) as c:
        assert c.get("/api/v1/auth/status").json()["setup_required"] is True
        assert c.get("/api/v1/movies").status_code == 200  # open until first user exists
        assert c.post("/api/v1/auth/setup", json={"username": "admin", "password": "short"}).status_code == 400
        r = c.post("/api/v1/auth/setup", json={"username": "admin", "password": "correct horse"})
        assert r.status_code == 200 and r.json()["is_admin"]
        assert c.post("/api/v1/auth/setup", json={"username": "x", "password": "another pass1"}).status_code in (401, 409)

        # logged in as admin (cookie); create a normal user
        assert c.post("/api/v1/users", json={"username": "kid", "password": "kidpassword", "is_admin": False}).status_code == 201

        anon = TestClient(app)
        assert anon.get("/api/v1/movies").status_code == 401
        assert anon.post("/api/v1/auth/login", json={"username": "kid", "password": "nope"}).status_code == 401
        assert anon.post("/api/v1/auth/login", json={"username": "kid", "password": "kidpassword"}).status_code == 200
        assert anon.get("/api/v1/movies").status_code == 200
        assert anon.get("/api/v1/users").status_code == 403          # not admin
        assert anon.post("/api/v1/users", json={"username": "z", "password": "zzzzzzzz"}).status_code == 403

        me = anon.get("/api/v1/auth/status").json()["user"]
        assert anon.put(f"/api/v1/users/{me['id']}/password", json={"password": "newpassword1"}).status_code == 200
        assert TestClient(app).post("/api/v1/auth/login", json={"username": "kid", "password": "newpassword1"}).status_code == 200

        admin_id = [u for u in c.get("/api/v1/users").json() if u["username"] == "admin"][0]["id"]
        assert c.delete(f"/api/v1/users/{admin_id}").status_code == 400   # last admin
    clean()


def test_tampered_cookie_and_lockout():
    clean()
    with TestClient(app) as c:
        c.post("/api/v1/auth/setup", json={"username": "admin", "password": "correct horse"})
        bad = TestClient(app, cookies={auth.COOKIE: "garbage"})
        assert bad.get("/api/v1/movies").status_code == 401
        anon = TestClient(app)
        codes = [anon.post("/api/v1/auth/login", json={"username": "admin", "password": "x"}).status_code for _ in range(6)]
        assert codes[:5] == [401] * 5 and codes[5] == 429
    clean()


def test_api_key_still_works_with_users():
    clean()
    with TestClient(app) as c:
        c.post("/api/v1/auth/setup", json={"username": "admin", "password": "correct horse"})
        old = settings.api_key
        settings.api_key = "k" * 20
        try:
            anon = TestClient(app)
            assert anon.get("/api/v1/movies", headers={"x-api-key": "k" * 20}).status_code == 200
            assert anon.get("/api/v1/movies", headers={"x-api-key": "wrong"}).status_code == 401
        finally:
            settings.api_key = old
    clean()
