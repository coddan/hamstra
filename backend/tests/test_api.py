from fastapi.testclient import TestClient

from app.main import app


def test_health_and_roots():
    with TestClient(app) as c:
        assert c.get("/api/health").json() == {"ok": True}
        kinds = {r["kind"] for r in c.get("/api/v1/system/rootfolders").json()}
        assert kinds == {"tv", "movies_kids", "movies_adults", "music"}


def test_movie_rules_configurable():
    with TestClient(app) as c:
        r = c.get("/api/v1/settings/movie-rules").json()
        assert "PG" in r["kids_certifications"]
        r["kids_certifications"] = ["G"]
        assert c.put("/api/v1/settings/movie-rules", json=r).json()["kids_certifications"] == ["G"]
        assert c.get("/api/v1/settings/movie-rules").json()["kids_certifications"] == ["G"]


def test_unknown_api_path_is_404_not_html():
    with TestClient(app) as c:
        r = c.get("/api/v1/nope")
        assert r.status_code in (404, 405) and "html" not in r.headers.get("content-type", "")


def test_hamstra_env_prefix_and_old_prefix_both_work(monkeypatch):
    import importlib

    from app import config

    monkeypatch.setenv("HAMSTRA_MUSIC_ROOT", "/new/prefix")
    monkeypatch.delenv("ARR_MUSIC_ROOT", raising=False)
    monkeypatch.setenv("ARR_IMPORT_MODE", "copy")             # the old prefix keeps working
    try:
        importlib.reload(config)
        assert str(config.Settings().music_root) == "/new/prefix" and config.Settings().import_mode == "copy"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_old_session_cookie_still_logs_in():
    from app.services import auth

    assert auth.COOKIE == "hamstra_session" and auth.LEGACY_COOKIE == "arr_session"
