from fastapi.testclient import TestClient

from app.indexers.torznab import Result
from app.main import app
from app.services.decision import Profile, Want, best, evaluate

MOVIE = Want("movie", "The Matrix", 1999)


def R(title, seeders=10, size=2_000_000_000, priority=25):
    return Result(title=title, seeders=seeders, size=size, download_url="magnet:x", priority=priority)


def test_sources_and_words():
    p = Profile(sources=["web-dl", "bluray"], source_order=["web-dl", "bluray"], reject_words=["hardsub"], prefer_words=["swedish"])
    assert "hdtv not allowed" in evaluate(R("The.Matrix.1999.1080p.HDTV.x264-G"), MOVIE, p).reasons
    assert "contains 'hardsub'" in evaluate(R("The.Matrix.1999.1080p.WEB-DL.HARDSUB.x264-G"), MOVIE, p).reasons
    web, blu = R("The.Matrix.1999.1080p.WEB-DL.x264-G"), R("The.Matrix.1999.1080p.BluRay.x264-G")
    assert best([web, blu], MOVIE, p).result is web          # profile ranks web-dl above bluray
    sw = R("The.Matrix.1999.SWEDISH.1080p.BluRay.x264-G")
    assert best([web, sw], MOVIE, p).result is sw             # preferred word outweighs the source rank
    p2 = Profile(source_order=["bluray", "web-dl"])
    assert best([web, blu], MOVIE, p2).result is blu


def test_remux_is_its_own_source():
    p = Profile(sources=["bluray"])
    assert "remux not allowed" in evaluate(R("The.Matrix.1999.1080p.BluRay.REMUX.AVC-G"), MOVIE, p).reasons
    assert evaluate(R("The.Matrix.1999.1080p.BluRay.x264-G"), MOVIE, p).accepted


def test_upgrades_disabled_and_priority_tiebreak():
    have = Want("movie", "The Matrix", 1999, current_resolution=720, has_file=True)
    assert "upgrades disabled" in evaluate(R("The.Matrix.1999.1080p.BluRay.x264-G"), have, Profile(upgrade_allowed=False)).reasons
    a, b = R("The.Matrix.1999.1080p.BluRay.x264-G", priority=40), R("The.Matrix.1999.1080p.BluRay.x264-G", priority=5)
    assert best([a, b], MOVIE, Profile()).result is b         # same release: lower priority number wins


def test_profile_api_and_indexer_patch():
    with TestClient(app) as c:
        base = c.get("/api/v1/profiles").json()
        assert any(p["is_default"] for p in base)
        body = {"name": "Web only", "resolutions": [1080], "cutoff": 1080, "sources": ["web-dl", "webrip"],
                "source_order": ["web-dl"], "prefer_words": "Swedish, Nordic", "reject_words": "hardsub"}
        r = c.post("/api/v1/profiles", json=body)
        assert r.status_code == 201
        p = r.json()
        assert p["prefer_words"] == "swedish,nordic" and p["source_order"][0] == "web-dl" and len(p["source_order"]) == 6
        assert c.post("/api/v1/profiles", json=body).status_code == 409
        assert c.post("/api/v1/profiles", json={**body, "name": "bad", "sources": ["vhs"]}).status_code == 400
        assert c.post("/api/v1/profiles", json={**body, "name": "bad2", "resolutions": []}).status_code == 400
        assert c.post(f"/api/v1/profiles/{p['id']}/default").json()["is_default"]
        assert [x["id"] for x in c.get("/api/v1/profiles").json() if x["is_default"]] == [p["id"]]
        assert c.delete(f"/api/v1/profiles/{p['id']}").status_code == 204   # default moves to another profile
        assert any(x["is_default"] for x in c.get("/api/v1/profiles").json())

        ix = c.post("/api/v1/indexers", json={"name": "t", "kind": "rss", "url": "http://127.0.0.1:9/x"})
        assert ix.status_code == 400  # unreachable feed fails the connection test


def test_indexer_priority_and_toggle():
    from app.db import SessionLocal
    from app.models import Indexer

    with TestClient(app) as c:
        with SessionLocal() as db:
            db.query(Indexer).filter_by(name="prio-test").delete()
            ix = Indexer(name="prio-test", kind="torznab", url="http://x", failures=3)
            db.add(ix)
            db.commit()
            iid = ix.id
        r = c.patch(f"/api/v1/indexers/{iid}", json={"priority": 5, "enabled": False}).json()
        assert r["priority"] == 5 and r["enabled"] is False
        assert c.patch(f"/api/v1/indexers/{iid}", json={"priority": 99}).status_code == 400
        r = c.patch(f"/api/v1/indexers/{iid}", json={"enabled": True}).json()
        assert r["enabled"] is True and r["failures"] == 0       # re-enabling clears the back-off
        c.delete(f"/api/v1/indexers/{iid}")
