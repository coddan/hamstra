import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

import httpx

NS = {"torznab": "http://torznab.com/schemas/2015/feed", "newznab": "http://www.newznab.com/DTD/2010/feeds/attributes/"}


@dataclass
class Result:
    title: str
    indexer: str = ""
    download_url: str = ""  # magnet or .torrent URL
    info_hash: str | None = None
    size: int = 0
    seeders: int = 0
    peers: int = 0
    published: datetime | None = None
    guid: str = ""
    priority: int = 25  # of the indexer it came from
    category: str = ""


def _attrs(item: ET.Element) -> dict[str, str]:
    out = {}
    for tag in ("torznab:attr", "newznab:attr"):
        for a in item.findall(tag, NS):
            out[a.get("name", "")] = a.get("value", "")
    return out


def parse_feed(xml_text: str, indexer: str = "") -> list[Result]:
    root = ET.fromstring(xml_text)
    err = root if root.tag == "error" else None
    if err is not None:
        raise ValueError(f"Indexer error {err.get('code')}: {err.get('description')}")
    results = []
    for item in root.iter("item"):
        a = _attrs(item)
        enclosure = item.find("enclosure")
        link = (item.findtext("link") or "").strip()
        magnet = a.get("magneturl") or (link if link.startswith("magnet:") else "")
        url = magnet or (enclosure.get("url") if enclosure is not None else "") or link
        size = a.get("size") or (enclosure.get("length") if enclosure is not None else "") or item.findtext("size") or "0"
        seeders = int(a.get("seeders", 0) or 0)
        peers = int(a.get("peers", 0) or 0)
        h = a.get("infohash")
        if not h and magnet:
            m = re.search(r"btih:([0-9a-fA-F]{40}|[A-Z2-7]{32})", magnet)
            h = m.group(1) if m else None
        pub = None
        pd = item.findtext("pubDate")
        if pd:
            try:
                from email.utils import parsedate_to_datetime
                pub = parsedate_to_datetime(pd).replace(tzinfo=None)
            except (TypeError, ValueError):
                pass
        results.append(Result(
            title=(item.findtext("title") or "").strip(), indexer=indexer, download_url=url,
            info_hash=h.lower() if h else None, size=int(size) if str(size).isdigit() else 0,
            seeders=seeders, peers=peers, published=pub, guid=(item.findtext("guid") or url),
            category=(item.findtext("category") or a.get("category") or "").strip(),
        ))
    return [r for r in results if r.title and r.download_url]


def _digits(imdb_id: str | None) -> str | None:
    return re.sub(r"\D", "", imdb_id) if imdb_id else None


def _fetch(indexer, params: dict) -> list[Result]:
    r = httpx.get(indexer.url, params=params, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return parse_feed(r.text, indexer.name)


def search(indexer, query: str | None = None, categories: str = "", season: int | None = None,
           episode: int | None = None, year: int | None = None, mode: str = "search",
           imdb_id: str | None = None, tvdb_id: int | None = None) -> list[Result]:
    """Query a Torznab indexer (mode: search|tvsearch|movie) or fetch an RSS feed.
    Tries an ID-based search first when IDs are known, then falls back to text."""
    if indexer.kind != "torznab":
        return _fetch(indexer, {})
    base: dict = {"t": mode, "apikey": indexer.api_key, "extended": 1}
    cats = "3000" if mode == "music" else (categories or indexer.categories)  # 3000 = Audio
    if cats:
        base["cat"] = cats
    if season is not None:
        base["season"] = season
    if episode is not None:
        base["ep"] = episode
    id_params = {}
    if mode == "movie" and _digits(imdb_id):
        id_params["imdbid"] = _digits(imdb_id)
    elif mode == "tvsearch" and tvdb_id:
        id_params["tvdbid"] = tvdb_id
    elif mode == "tvsearch" and _digits(imdb_id):
        id_params["imdbid"] = _digits(imdb_id)
    if id_params:
        try:
            found = _fetch(indexer, {**base, **id_params})
            if found:
                return found
        except (httpx.HTTPError, ValueError):
            pass  # indexer may not support this ID type; fall back to text
    text = dict(base)
    if query:
        text["q"] = query
    if year and mode == "movie":
        text["year"] = year
    return _fetch(indexer, text)


def test_indexer(indexer) -> None:
    if indexer.kind == "torznab":
        r = httpx.get(indexer.url, params={"t": "caps", "apikey": indexer.api_key}, timeout=20, follow_redirects=True)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        if root.tag == "error":
            raise ValueError(f"{root.get('code')}: {root.get('description')}")
        if root.tag != "caps":
            raise ValueError("Not a Torznab endpoint")
    else:
        search(indexer)
