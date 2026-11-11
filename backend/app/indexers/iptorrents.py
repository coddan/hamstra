"""IPTorrents: logs in with browser cookies and parses the HTML search page."""
import html
import re
from urllib.parse import quote

import httpx

from .torznab import Result

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")
MUSIC_CATEGORIES = "80,3,93"  # Music/Flac, Music/Audio, Music/Packs
ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
TITLE = re.compile(r'<a class="[^"]*hv"[^>]*href="/t/(\d+)"[^>]*>(.*?)</a>', re.S)
DL = re.compile(r'href="(/download\.php/[^"]+\.torrent)"')
TAIL = re.compile(r"<td>([\d.,]+\s*[KMGT]?B)<td>(\d+)<td>(\d+)<td>(\d+)\s*$", re.S)
UNITS = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}


class IptError(Exception):
    pass


def _size(text: str) -> int:
    n, unit = text.replace(",", "").split()
    return int(float(n) * UNITS[unit.upper()])


def parse_page(page: str, indexer) -> list[Result]:
    if 'id="torrents"' not in page:
        low = page.lower()
        if "just a moment" in low or "cf-chl" in low or "challenge-platform" in low:
            raise IptError("Cloudflare challenge: refresh the cf_clearance cookie (same IP and user agent as the browser)")
        if 'name="password"' in low or "login.php" in low:
            raise IptError("Not logged in: cookie (uid/pass) rejected or expired")
        return []
    base = indexer.url.rstrip("/")
    out = []
    for row in ROW.findall(page[page.index('id="torrents"'):]):
        t, d, tail = TITLE.search(row), DL.search(row), TAIL.search(row)
        if not (t and d and tail):
            continue
        out.append(Result(
            title=html.unescape(re.sub(r"<[^>]+>", "", t.group(2))).strip(), indexer=indexer.name,
            download_url=base + quote(html.unescape(d.group(1)), safe="/:()%[]!'~,+@=&;-._"),
            size=_size(tail.group(1)), seeders=int(tail.group(3)), peers=int(tail.group(4)), guid=t.group(1),
            category=html.unescape((re.search(r'<img[^>]*alt="([^"]*)"', row) or [None, ""])[1]),
        ))
    return out


def _client(indexer) -> httpx.Client:
    return httpx.Client(
        headers={"Cookie": indexer.cookie, "User-Agent": indexer.user_agent or DEFAULT_UA},
        timeout=30, follow_redirects=True,
    )


def search(indexer, query=None, categories="", season=None, episode=None, year=None, mode="search",
           imdb_id=None, tvdb_id=None) -> list[Result]:
    if mode == "tvsearch" and query and season is not None:
        query = f"{query} S{season:02d}" + (f"E{episode:02d}" if episode is not None else "")
    params: dict = {"q": query or "", "qf": "all"}
    if query:
        params["o"] = "seeders"  # without a query we want the newest uploads (default order)
    cats = MUSIC_CATEGORIES if mode == "music" else (categories or indexer.categories)
    for c in cats.split(","):
        if c.strip().isdigit():
            params[c.strip()] = ""
    with _client(indexer) as c:
        r = c.get(f"{indexer.url.rstrip('/')}/t", params=params)
    if r.status_code in (403, 503) and "just a moment" in r.text.lower():
        raise IptError("Cloudflare challenge: refresh the cf_clearance cookie")
    r.raise_for_status()
    return parse_page(r.text, indexer)


def test(indexer) -> None:
    with _client(indexer) as c:
        r = c.get(f"{indexer.url.rstrip('/')}/t", params={"q": "test", "qf": "all"})
    if r.status_code in (403, 503) and "just a moment" in r.text.lower():
        raise IptError("Cloudflare challenge: refresh the cf_clearance cookie")
    r.raise_for_status()
    if 'id="torrents"' not in r.text:
        parse_page(r.text, indexer)
        raise IptError("Unexpected page (not the torrent list)")


def download(indexer, url: str) -> bytes:
    with _client(indexer) as c:
        r = c.get(url)
    r.raise_for_status()
    return r.content
