import json

import httpx

from app.db import SessionLocal
from app.models import Movie, Setting
from app.services import subtitles
from fastapi.testclient import TestClient
from app.main import app


def make_transport(calls, quota_after=99):
    n = {"dl": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path, dict(req.url.params)))
        if req.url.path.endswith("/login"):
            return httpx.Response(200, json={"token": "T", "base_url": "api.opensubtitles.com"})
        if req.url.path.endswith("/subtitles"):
            lang = req.url.params["languages"]
            if lang == "en" and req.url.params.get("imdb_id") == "0000002":
                return httpx.Response(200, json={"data": []})            # nothing in English for this film
            return httpx.Response(200, json={"data": [
                {"attributes": {"language": lang, "download_count": 5, "hearing_impaired": True, "files": [{"file_id": 1}]}},
                {"attributes": {"language": lang, "download_count": 50, "hearing_impaired": False, "files": [{"file_id": 2}]}},
                {"attributes": {"language": "xx", "download_count": 999, "files": [{"file_id": 3}]}}]})
        if req.url.path.endswith("/download"):
            n["dl"] += 1
            if n["dl"] > quota_after:
                return httpx.Response(406, json={"message": "quota"})
            return httpx.Response(200, json={"link": f"https://dl.example/{req.content.decode()}"})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_best_choice():
    r = [{"attributes": {"language": "sv", "download_count": 5, "hearing_impaired": True, "files": [{"file_id": 1}]}},
         {"attributes": {"language": "sv", "download_count": 50, "hearing_impaired": False, "files": [{"file_id": 2}]}},
         {"attributes": {"language": "en", "download_count": 99, "files": [{"file_id": 3}]}}]
    assert subtitles.best(r, "sv") == 2                      # most downloaded, not hearing-impaired, right language
    assert subtitles.best(r, "de") is None


def test_missing_languages(tmp_path):
    v = tmp_path / "Film (2020).mkv"
    v.write_text("x")
    (tmp_path / "Film (2020).sv.srt").write_text("x")
    (tmp_path / "Other.en.srt").write_text("x")
    assert subtitles.missing_languages(v, ["sv", "en"]) == ["en"]


def test_run_downloads_and_respects_limits(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(subtitles.httpx, "get", lambda url, **kw: httpx.Response(200, content=b"1\n00:00:01,000 --> 00:00:02,000\nHej\n", request=httpx.Request("GET", url)))
    a, b = tmp_path / "A (2020)", tmp_path / "B (2021)"
    a.mkdir(); b.mkdir()
    (a / "A (2020).mkv").write_text("x"); (b / "B (2021).mkv").write_text("x")
    with TestClient(app), SessionLocal() as db:
        db.query(Movie).filter(Movie.tmdb_id.in_([8001, 8002])).delete()
        db.add_all([Movie(tmdb_id=8001, title="A", year=2020, has_file=True, path=str(a), imdb_id="tt0000001"),
                    Movie(tmdb_id=8002, title="B", year=2021, has_file=True, path=str(b), imdb_id="tt0000002")])
        db.merge(Setting(key="subtitles", value=json.dumps({"enabled": True, "api_key": "k", "username": "u", "password": "p", "languages": "sv,en", "limit_per_run": 10})))
        db.merge(Setting(key=subtitles.TRIED_KEY, value="{}"))
        db.commit()
        client = subtitles.OpenSubtitles("k", "u", "p", transport=make_transport(calls))
        out = subtitles.run(db, client)
        assert out["downloaded"] == 3 and out["not_found"] == 1                      # B has no English subtitle
        assert (a / "A (2020).sv.srt").read_text().endswith("Hej\n") and (a / "A (2020).en.srt").exists() and (b / "B (2021).sv.srt").exists()
        assert not (b / "B (2021).en.srt").exists()
        out2 = subtitles.run(db, subtitles.OpenSubtitles("k", "u", "p", transport=make_transport(calls)))
        assert out2["downloaded"] == 0 and out2["skipped"] == 1                       # the missing one is not asked again for 2 weeks

        (a / "A (2020).sv.srt").unlink()
        limited = subtitles.run(db, subtitles.OpenSubtitles("k", "u", "p", transport=make_transport(calls)), limit=0 or 1)
        assert limited["downloaded"] == 1
        (a / "A (2020).en.srt").unlink(); (a / "A (2020).sv.srt").unlink(missing_ok=True)
        quota = subtitles.run(db, subtitles.OpenSubtitles("k", "u", "p", transport=make_transport(calls, quota_after=0)), limit=5)
        assert quota["downloaded"] == 0 and "quota" in quota["stopped"]               # stops cleanly when the daily quota is used up
        db.query(Movie).filter(Movie.tmdb_id.in_([8001, 8002])).delete(); db.commit()


def test_disabled_and_missing_credentials():
    with TestClient(app), SessionLocal() as db:
        db.merge(Setting(key="subtitles", value=json.dumps({"enabled": False})))
        db.commit()
        assert subtitles.run(db) == {"disabled": True}
        db.merge(Setting(key="subtitles", value=json.dumps({"enabled": True})))
        db.commit()
        assert "API key" in subtitles.run(db)["error"]
        db.merge(Setting(key="subtitles", value=json.dumps({"enabled": False})))
        db.commit()
