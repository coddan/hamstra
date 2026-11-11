from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.indexers import hdbits, iptorrents
from app.main import app
from app.services import seeding


def test_iptorrents_parse():
    page = (Path(__file__).parent / "fixtures" / "ipt_search.html").read_text(encoding="utf8")
    ix = SimpleNamespace(name="IPT", url="https://iptorrents.com")
    res = iptorrents.parse_page(page, ix)
    assert len(res) >= 3
    r = res[0]
    assert r.title and r.download_url.startswith("https://iptorrents.com/download.php/")
    assert r.download_url.endswith(".torrent") and " " not in r.download_url
    assert r.size > 0 and r.seeders >= 0
    assert any(x.seeders > 0 for x in res)


def test_iptorrents_errors():
    ix = SimpleNamespace(name="IPT", url="https://iptorrents.com")
    with pytest.raises(iptorrents.IptError, match="Cloudflare"):
        iptorrents.parse_page("<html><title>Just a moment...</title></html>", ix)
    with pytest.raises(iptorrents.IptError, match="Not logged in"):
        iptorrents.parse_page('<form><input name="password"></form>', ix)


def test_hdbits_parse():
    ix = SimpleNamespace(name="HDB", url="", api_key="PK")
    rows = [{"id": 5, "hash": "ABCDEF0123456789ABCDEF0123456789ABCDEF01", "name": "The.Matrix.1999.1080p.BluRay.x264-G",
             "size": 9_000_000_000, "seeders": 12, "leechers": 1, "utadded": 1700000000}]
    r = hdbits.parse_rows(rows, ix)[0]
    assert r.info_hash == "abcdef0123456789abcdef0123456789abcdef01"
    assert r.download_url == "https://hdbits.org/download.php?id=5&passkey=PK"
    assert r.seeders == 12


def test_kinds_and_validation():
    with TestClient(app) as c:
        kinds = {k["kind"]: k for k in c.get("/api/v1/indexers/kinds").json()}
        assert set(kinds) == {"torznab", "rss", "hdbits", "iptorrents", "archiveorg"}
        assert {"username", "api_key"} <= {f["name"] for f in kinds["hdbits"]["fields"]}
        assert {"cookie", "user_agent"} <= {f["name"] for f in kinds["iptorrents"]["fields"]}
        r = c.post("/api/v1/indexers", json={"name": "hdb", "kind": "hdbits", "api_key": "x"})
        assert r.status_code == 400 and "Username" in r.json()["detail"]
        assert c.post("/api/v1/indexers", json={"name": "x", "kind": "nope"}).status_code == 400


def test_seeding_rules():
    either = {"ratio": 1.0, "hours": 72, "mode": "either"}
    assert seeding.satisfied(either, 1.0, 0) and seeding.satisfied(either, 0, 72 * 3600)
    assert not seeding.satisfied(either, 0.5, 3600)
    both = {**either, "mode": "both"}
    assert not seeding.satisfied(both, 2.0, 3600) and seeding.satisfied(both, 2.0, 72 * 3600)
