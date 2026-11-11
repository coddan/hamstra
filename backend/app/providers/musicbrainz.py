"""MusicBrainz (metadata) and Cover Art Archive (covers). Free, no key; asks for a descriptive User-Agent and 1 request/second."""
import threading
import time

import httpx

BASE = "https://musicbrainz.org/ws/2"
HEADERS = {"User-Agent": "Hamstra/1.0 (self-hosted)", "Accept": "application/json"}
MIN_GAP = 1.1
_lock = threading.Lock()
_last = 0.0


class MusicBrainzError(Exception):
    pass


def _get(path: str, **params) -> dict:
    global _last
    r = None
    for attempt in range(4):
        with _lock:
            wait = _last + MIN_GAP - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _last = time.monotonic()
        r = httpx.get(f"{BASE}{path}", params={**params, "fmt": "json"}, headers=HEADERS, timeout=20)
        if r.status_code in (429, 503):  # rate limited / busy: wait and retry
            time.sleep(2 + attempt * 2)
            continue
        break
    if r is None or r.status_code != 200:
        raise MusicBrainzError(f"MusicBrainz {r.status_code if r is not None else '?'}")
    return r.json()


def cover_url(mbid: str) -> str:
    return f"https://coverartarchive.org/release-group/{mbid}/front-250"


def _artist_name(rg: dict) -> str:
    return "".join(f"{a.get('name', '')}{a.get('joinphrase', '')}" for a in rg.get("artist-credit", []) if isinstance(a, dict)) or "Unknown"


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and date[:4].isdigit() else None


def _album(rg: dict) -> dict:
    credit = next((a for a in rg.get("artist-credit", []) if isinstance(a, dict) and a.get("artist")), None)
    secondary = rg.get("secondary-types") or []
    kind = rg.get("primary-type") or "Album"
    return {
        "mbid": rg["id"], "title": rg["title"], "artist": _artist_name(rg),
        "artist_mbid": credit["artist"]["id"] if credit else None, "year": _year(rg.get("first-release-date")),
        "kind": f"{kind} ({', '.join(secondary)})" if secondary else kind, "cover_url": cover_url(rg["id"]),
    }


def search_albums(query: str, limit: int = 20) -> list[dict]:
    return [_album(r) for r in _get("/release-group", query=query, limit=limit).get("release-groups", [])]


def search_artists(query: str, limit: int = 10) -> list[dict]:
    return [
        {"mbid": a["id"], "name": a["name"], "disambiguation": a.get("disambiguation", ""), "country": a.get("country", ""),
         "type": a.get("type", "")}
        for a in _get("/artist", query=query, limit=limit).get("artists", [])
    ]


def artist_albums(artist_mbid: str) -> list[dict]:
    """All albums and EPs of an artist (newest first)."""
    out, offset = [], 0
    while offset < 300:
        data = _get("/release-group", artist=artist_mbid, type="album|ep", limit=100, offset=offset)
        groups = data.get("release-groups", [])
        out.extend(_album(rg) for rg in groups)
        offset += 100
        if offset >= data.get("release-group-count", 0) or not groups:
            break
    return sorted(out, key=lambda a: (a["year"] or 0), reverse=True)
