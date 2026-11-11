"""Trakt public lists (needs the user's own client id: https://trakt.tv/oauth/applications)."""
import re

import httpx

BASE = "https://api.trakt.tv"


class TraktError(Exception):
    pass


def _get(path: str, client_id: str, **params):
    if not client_id:
        raise TraktError("Set the Trakt client id under Settings → Library")
    r = httpx.get(f"{BASE}{path}", params=params, timeout=20, follow_redirects=True,
                  headers={"trakt-api-version": "2", "trakt-api-key": client_id, "Content-Type": "application/json"})
    if r.status_code == 404:
        raise TraktError("List not found (is it public?)")
    if r.status_code in (401, 403):
        raise TraktError("Trakt rejected the client id (or the list is private)")
    r.raise_for_status()
    return r.json()


def parse_url(url: str) -> str:
    """API path for a trakt.tv list or chart URL."""
    u = url.strip()
    m = re.search(r"trakt\.tv/users/([^/]+)/lists/([^/?#]+)", u)
    if m:
        return f"/users/{m.group(1)}/lists/{m.group(2)}/items"
    m = re.search(r"trakt\.tv/(movies|shows)/(trending|popular|anticipated|watched|collected|played)", u)
    if m:
        return f"/{m.group(1)}/{m.group(2)}"
    raise TraktError("Use a link like trakt.tv/users/NAME/lists/LIST or trakt.tv/movies/trending")


def list_items(url: str, client_id: str, limit: int = 100) -> list[dict]:
    """[{type: movie|show, title, year, tmdb, imdb}]"""
    data = _get(parse_url(url), client_id, limit=limit)
    out = []
    for it in data:
        kind = it.get("type") or ("movie" if "movie" in it else "show" if "show" in it else None)
        body = it.get(kind) if kind else None
        if body is None and "title" in it:           # charts like /movies/popular return bare movies
            body, kind = it, "movie" if "/movies/" in parse_url(url) else "show"
        if not body or kind not in ("movie", "show"):
            continue
        ids = body.get("ids", {})
        out.append({"type": kind, "title": body.get("title"), "year": body.get("year"), "tmdb": ids.get("tmdb"), "imdb": ids.get("imdb")})
    return out
