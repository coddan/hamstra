"""HDBits JSON API (username + passkey). https://hdbits.org/api/torrents"""
from datetime import datetime

import httpx

from .torznab import Result

BASE = "https://hdbits.org"
CAT_MOVIE, CAT_TV, CAT_MUSIC = 1, 2, 4
CATEGORY_NAMES = {1: "Movie", 2: "TV", 3: "Documentary", 4: "Music", 5: "Sport", 6: "Audio", 7: "XXX", 8: "Misc/Demo"}


def _post(indexer, payload: dict) -> list[dict]:
    body = {"username": indexer.username, "passkey": indexer.api_key, **payload}
    r = httpx.post(f"{(indexer.url or BASE).rstrip('/')}/api/torrents", json=body, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != 0:
        raise ValueError(f"HDBits: {data.get('message') or 'error status ' + str(data.get('status'))}")
    return data.get("data", [])


def parse_rows(rows: list[dict], indexer) -> list[Result]:
    base = (indexer.url or BASE).rstrip("/")
    out = []
    for t in rows:
        added = None
        if t.get("utadded"):
            added = datetime.utcfromtimestamp(int(t["utadded"]))
        out.append(Result(
            title=t["name"], indexer=indexer.name,
            download_url=f"{base}/download.php?id={t['id']}&passkey={indexer.api_key}",
            info_hash=(t.get("hash") or "").lower() or None, size=int(t.get("size", 0)),
            seeders=int(t.get("seeders", 0)), peers=int(t.get("leechers", 0)),
            published=added, guid=str(t["id"]), category=CATEGORY_NAMES.get(int(t.get("type_category") or 0), ""),
        ))
    return out


def search(indexer, query=None, categories="", season=None, episode=None, year=None, mode="search",
           imdb_id=None, tvdb_id=None) -> list[Result]:
    payload: dict = {"limit": 100}
    ids: dict = {}
    if mode == "tvsearch":
        payload["category"] = [CAT_TV]
        if tvdb_id:
            ids["tvdb"] = {"id": int(tvdb_id)}
            if season is not None:
                ids["tvdb"]["season"] = season
            if episode is not None:
                ids["tvdb"]["episode"] = episode
        if query and season is not None:
            query = f"{query} S{season:02d}" + (f"E{episode:02d}" if episode is not None else "")
    elif mode == "music":
        payload["category"] = [CAT_MUSIC]
    elif mode == "movie":
        payload["category"] = [CAT_MOVIE]
        digits = "".join(c for c in (imdb_id or "") if c.isdigit())
        if digits:
            ids["imdb"] = {"id": int(digits)}
    cats = [int(c) for c in (categories or indexer.categories).split(",") if c.strip().isdigit()] if mode != "music" else []
    if cats:
        payload["category"] = cats
    if ids:
        found = parse_rows(_post(indexer, {**payload, **ids}), indexer)
        if found:
            return found
    if query:
        payload["search"] = query
    return parse_rows(_post(indexer, payload), indexer)


def test(indexer) -> None:
    _post(indexer, {"limit": 1})


def download(indexer, url: str) -> bytes:
    r = httpx.get(url, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.content
