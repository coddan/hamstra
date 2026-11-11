from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.indexers import archiveorg, iptorrents, registry
from app.main import app

IX = SimpleNamespace(name="archive.org", url="", categories="", kind="archiveorg")
DOCS = [
    {"identifier": "PinkFloyd_212", "title": "The Wall", "creator": "Pink Floyd", "mediatype": "audio", "item_size": 3828128,
     "downloads": 963, "publicdate": "2020-01-02T03:04:05Z"},
    {"identifier": "notorrent", "title": ["Some Film"], "mediatype": "movies", "item_size": "700000000"},
    {"title": "no identifier"},
]


def test_parse_docs():
    r = archiveorg.parse_docs(DOCS, IX)
    assert len(r) == 2
    assert r[0].title == "Pink Floyd - The Wall"                       # artist added for music matching
    assert r[0].download_url == "https://archive.org/download/PinkFloyd_212/PinkFloyd_212_archive.torrent"
    assert r[0].seeders == 1 and r[0].category == "audio" and r[0].published.year == 2020
    assert r[1].title == "Some Film" and r[1].size == 700000000


def test_search_modes_pick_media_types(monkeypatch):
    seen = []
    monkeypatch.setattr(archiveorg, "_search", lambda ix, q, types, rows=50: seen.append((q, types)) or [])
    archiveorg.search(IX, "pink floyd the wall", mode="music")
    archiveorg.search(IX, "Some Show", season=2, episode=3, mode="tvsearch")
    archiveorg.search(IX, "anything", categories="texts,software")
    assert seen[0] == ("(title:pink OR creator:pink) AND (title:floyd OR creator:floyd) AND (title:the OR creator:the) AND (title:wall OR creator:wall)", ["audio", "etree"])
    assert seen[1][0].startswith("(title:Some OR creator:Some) AND (title:Show OR creator:Show)") and seen[1][1] == ["movies"]
    assert seen[2] == ("(title:anything OR creator:anything)", ["texts", "software"])
    assert archiveorg.search(IX, "") == []


def test_registered_without_credentials():
    kinds = {k["kind"]: k for k in registry.public_kinds()}
    assert "archiveorg" in kinds and all(not f["required"] for f in kinds["archiveorg"]["fields"])
    assert iptorrents.MUSIC_CATEGORIES == "80,3,93"


def test_slow_sorted_query_falls_back(monkeypatch):
    import httpx

    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(any(k == "sort[]" for k, _ in params))
        if calls[-1]:
            raise httpx.ReadTimeout("slow")
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"response": {"docs": [{"identifier": "x"}]}})
    monkeypatch.setattr(archiveorg.httpx, "get", fake_get)
    assert archiveorg._search(IX, "broad query", []) == [{"identifier": "x"}]
    assert calls == [True, False]                                       # sorted first, then without sorting
