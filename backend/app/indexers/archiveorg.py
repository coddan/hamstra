"""archive.org: free, no login. Every item has a .torrent with web seeds, so it downloads even without peers."""
import functools
import re
from datetime import datetime

import httpx

from .torznab import Result

BASE = "https://archive.org"
UA = {"User-Agent": "Hamstra/1.0"}
MODE_TYPES = {"movie": ["movies"], "tvsearch": ["movies"], "music": ["audio", "etree"]}  # what each kind of search may return
ALL_TYPES = ["audio", "etree", "movies", "texts", "software", "image", "data"]


def _search(indexer, query: str, mediatypes: list[str], rows: int = 50, sort: bool = True) -> list[dict]:
    q = f"({query})"
    if mediatypes:
        q += " AND (" + " OR ".join(f"mediatype:{t}" for t in mediatypes) + ")"
    params = [("q", q), ("rows", rows), ("output", "json"),
              *[("fl[]", f) for f in ("identifier", "title", "creator", "mediatype", "item_size", "downloads", "publicdate")]]
    if sort:
        params.append(("sort[]", "downloads desc"))  # most popular first; slow for very broad queries
    url = f"{(indexer.url or BASE).rstrip('/')}/advancedsearch.php"
    try:
        r = httpx.get(url, params=params, headers=UA, timeout=40)
    except httpx.TimeoutException:
        if not sort:
            raise
        return _search(indexer, query, mediatypes, rows, sort=False)  # the sorted query was too heavy: take archive.org's own ranking
    r.raise_for_status()
    return r.json().get("response", {}).get("docs", [])


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def parse_docs(docs: list[dict], indexer) -> list[Result]:
    base = (indexer.url or BASE).rstrip("/")
    out = []
    for d in docs:
        ident = d.get("identifier")
        if not ident:
            continue
        title = str(_first(d.get("title")) or ident)
        creator = _first(d.get("creator"))
        if d.get("mediatype") in ("audio", "etree") and creator and str(creator).lower() not in title.lower():
            title = f"{creator} - {title}"   # music matching needs the artist in the name
        pub = None
        if d.get("publicdate"):
            try:
                pub = datetime.fromisoformat(d["publicdate"].replace("Z", ""))
            except ValueError:
                pass
        out.append(Result(
            title=title, indexer=indexer.name, download_url=f"{base}/download/{ident}/{ident}_archive.torrent",
            size=int(d.get("item_size") or 0), seeders=1, peers=int(d.get("downloads") or 0),  # web seed: always available
            published=pub, guid=ident, category=str(d.get("mediatype") or ""),
        ))
    return out


def search(indexer, query=None, categories="", season=None, episode=None, year=None, mode="search",
           imdb_id=None, tvdb_id=None) -> list[Result]:
    types = MODE_TYPES.get(mode) or [t.strip() for t in (categories or indexer.categories).split(",") if t.strip()]
    if mode == "tvsearch" and query and season is not None:
        query = f"{query} S{season:02d}" + (f"E{episode:02d}" if episode is not None else "")
    words = re.findall(r"[\w']+", query or "")
    if not words:
        return []
    # archive.org matches any word anywhere (descriptions, crawl lists) by default: require every word in the title or creator
    q = " AND ".join(f"(title:{w} OR creator:{w})" for w in words)
    return parse_docs(_search(indexer, q, types), indexer)


def test(indexer) -> None:
    # the search endpoint is slow and erratic (0.5-10 s); a tiny metadata call proves the service is reachable
    r = httpx.get(f"{(indexer.url or BASE).rstrip('/')}/metadata/PinkFloyd_212/metadata/title", headers=UA, timeout=20)
    r.raise_for_status()


def download(indexer, url: str) -> bytes:
    r = httpx.get(url, headers=UA, timeout=30, follow_redirects=True)
    r.raise_for_status()
    if not r.content.startswith(b"d"):
        raise ValueError("archive.org did not return a torrent for this item")
    return r.content


@functools.lru_cache(maxsize=512)
def _file_formats(ident: str, base: str) -> tuple[str, ...]:
    r = httpx.get(f"{base}/metadata/{ident}/files", headers=UA, timeout=15)
    r.raise_for_status()
    return tuple(sorted({str(f.get("format", "")).lower() for f in r.json().get("result", [])}))


def audio_quality_hint(ident: str, base: str = BASE) -> str | None:
    """What an archive.org audio item really contains, as a category hint ('Music/Flac', 'Music/MP3 320'...).
    Titles on archive.org almost never say, so the item's file list is the only reliable source."""
    try:
        formats = _file_formats(ident, base)
    except (httpx.HTTPError, ValueError):
        return None
    joined = " | ".join(formats)
    if "24bit flac" in joined:
        return "Music/Flac 24bit"
    if any(k in joined for k in ("flac", "apple lossless", "wave")):
        return "Music/Flac"
    for key, label in (("320kbps mp3", "320"), ("vbr mp3", "v2"), ("256kbps mp3", "256"), ("192kbps mp3", "192")):
        if key in joined:
            return f"Music/MP3 {label}"
    return "Music/MP3 128" if "mp3" in joined else None
