import httpx

from ..config import settings

BASE = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w342"


class TmdbError(Exception):
    pass


def _request(path: str, **params):
    key = settings.tmdb_api_key
    if not key:
        raise TmdbError("HAMSTRA_TMDB_API_KEY is not set")
    headers, query = {}, dict(params)
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    else:
        query["api_key"] = key
    r = httpx.get(f"{BASE}{path}", headers=headers, params=query, timeout=15)
    if r.status_code != 200:
        raise TmdbError(f"TMDB {r.status_code}: {r.text[:200]}")
    return r.json()


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and len(date) >= 4 and date[:4].isdigit() else None


def search_movies(query: str, year: int | None = None, language: str = "en-US") -> list[dict]:
    params = {"query": query, "language": language}
    if year:
        params["year"] = year
    return [
        {
            "tmdb_id": m["id"],
            "title": m["title"],
            "year": _year(m.get("release_date")),
            "overview": m.get("overview"),
            "poster_url": IMG + m["poster_path"] if m.get("poster_path") else None,
        }
        for m in _request("/search/movie", **params)["results"]
    ]


def movie_details(tmdb_id: int) -> dict:
    m = _request(f"/movie/{tmdb_id}", append_to_response="release_dates,external_ids")
    cert = None
    for country in m.get("release_dates", {}).get("results", []):
        if country["iso_3166_1"] in ("SE", "US"):
            certs = [r["certification"] for r in country["release_dates"] if r.get("certification")]
            if certs:
                cert = certs[0]
                if country["iso_3166_1"] == "SE":
                    break
    return {
        "tmdb_id": m["id"],
        "title": m["title"],
        "year": _year(m.get("release_date")),
        "overview": m.get("overview"),
        "poster_url": IMG + m["poster_path"] if m.get("poster_path") else None,
        "certification": cert,
        "imdb_id": m.get("imdb_id") or (m.get("external_ids") or {}).get("imdb_id"),
        "release_date": m.get("release_date") or None,
        "genres": [g["name"] for g in m.get("genres", [])],
    }


def find_movie_by_imdb(imdb_id: str) -> list[dict]:
    data = _request(f"/find/{imdb_id}", external_source="imdb_id")
    return [
        {
            "tmdb_id": m["id"], "title": m["title"], "year": _year(m.get("release_date")),
            "overview": m.get("overview"),
            "poster_url": IMG + m["poster_path"] if m.get("poster_path") else None,
        }
        for m in data.get("movie_results", [])
    ]


def search_movies_ext(query: str, year: int | None = None, language: str = "en-US") -> list[dict]:
    params = {"query": query, "language": language}
    if year:
        params["year"] = year
    return [
        {
            "tmdb_id": m["id"], "title": m["title"], "original_title": m.get("original_title") or m["title"],
            "year": _year(m.get("release_date")), "overview": m.get("overview"),
            "poster_url": IMG + m["poster_path"] if m.get("poster_path") else None,
        }
        for m in _request("/search/movie", **params)["results"]
    ]


def list_items(list_id: str) -> list[dict]:
    """Items of a public TMDB list (v4 API): [{media_type, id, title, year}]."""
    out, page = [], 1
    while page <= 20:
        r = httpx.get(f"https://api.themoviedb.org/4/list/{list_id}", params={"page": page},
                      headers={"Authorization": f"Bearer {settings.tmdb_api_key}"}, timeout=20)
        if r.status_code == 404:
            raise TmdbError("List not found (is it public?)")
        if r.status_code != 200:
            raise TmdbError(f"TMDB {r.status_code}: {r.text[:200]}")
        data = r.json()
        for it in data.get("results", []):
            out.append({"media_type": it.get("media_type"), "id": it["id"], "title": it.get("title") or it.get("name"),
                        "year": _year(it.get("release_date") or it.get("first_air_date"))})
        if page >= data.get("total_pages", 1):
            break
        page += 1
    return out


def tv_imdb_id(tmdb_tv_id: int) -> str | None:
    return _request(f"/tv/{tmdb_tv_id}/external_ids").get("imdb_id")


def search_tv(query: str, language: str = "en-US") -> list[dict]:
    """TMDB TV search (knows Swedish and other translated titles, which TVmaze does not)."""
    return [
        {"tmdb_id": t["id"], "title": t["name"], "original_title": t.get("original_name") or t["name"],
         "year": _year(t.get("first_air_date"))}
        for t in _request("/search/tv", query=query, language=language)["results"]
    ]
