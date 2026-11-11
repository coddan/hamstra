import re
import threading
import time

import httpx

BASE = "https://api.tvmaze.com"


_lock = threading.Lock()
_last = 0.0
MIN_GAP = 0.55  # TVmaze allows about 20 calls per 10 seconds


def _request(path: str, **params) -> httpx.Response:
    """GET with a minimum gap between calls and patient retries when TVmaze answers 429."""
    global _last
    r = None
    for attempt in range(4):
        with _lock:
            wait = _last + MIN_GAP - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _last = time.monotonic()
        r = httpx.get(f"{BASE}{path}", params=params, timeout=15, follow_redirects=True)
        if r.status_code != 429:
            return r
        time.sleep(float(r.headers.get("Retry-After", 2)) + attempt * 2)
    return r


def _get(path: str, **params):
    r = _request(path, **params)
    r.raise_for_status()
    return r.json()


def _show(s: dict) -> dict:
    return {
        "tvmaze_id": s["id"],
        "title": s["name"],
        "year": int(s["premiered"][:4]) if s.get("premiered") else None,
        "overview": re.sub(r"<[^>]+>", "", s.get("summary") or "") or None,
        "poster_url": (s.get("image") or {}).get("medium"),
        "status": s.get("status"),
        "imdb_id": (s.get("externals") or {}).get("imdb"),
        "tvdb_id": (s.get("externals") or {}).get("thetvdb"),
        "genres": s.get("genres") or [],
    }


def search_shows(query: str) -> list[dict]:
    return [_show(r["show"]) for r in _get("/search/shows", q=query)]


def show_details(tvmaze_id: int) -> dict:
    return _show(_get(f"/shows/{tvmaze_id}"))


def episodes(tvmaze_id: int) -> list[dict]:
    """Regular episodes keep their season and number. Specials (TVmaze gives them no number) become season 0,
    numbered 1..N by air date; the caller keeps those numbers stable on later refreshes."""
    raw = _get(f"/shows/{tvmaze_id}/episodes", specials=1)
    out = [
        {"season": e["season"], "number": e["number"], "title": e["name"], "air_date": e.get("airdate") or None}
        for e in raw if e.get("number") is not None
    ]
    specials = sorted((e for e in raw if e.get("number") is None), key=lambda e: (e.get("airdate") or "9999", e["id"]))
    out += [{"season": 0, "number": i, "title": e["name"], "air_date": e.get("airdate") or None, "special": True}
            for i, e in enumerate(specials, 1)]
    return out


def lookup_imdb(imdb_id: str) -> list[dict]:
    r = _request("/lookup/shows", imdb=imdb_id)
    return [_show(r.json())] if r.status_code == 200 else []
