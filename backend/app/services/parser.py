import re
from dataclasses import dataclass, field
from datetime import date

_SEP = re.compile(r"[._]+")

RESOLUTION = [(re.compile(p, re.I), v) for p, v in [
    (r"\b(2160p|4k|uhd)\b", 2160), (r"\b1080[pi]\b", 1080), (r"\b720p\b", 720),
    (r"\b576p\b", 576), (r"\b(480p|480i)\b", 480),
]]
SOURCE = [(re.compile(p, re.I), v) for p, v in [
    (r"\b(bdremux|remux)\b", "remux"), (r"\b(blu-?ray|bdrip|brrip)\b", "bluray"),
    (r"\bweb-?dl\b", "web-dl"), (r"\bweb-?rip\b", "webrip"), (r"\bweb\b", "web-dl"),
    (r"\bhdtv\b", "hdtv"), (r"\bdvd(rip)?\b", "dvd"),
    (r"\b(cam|hdcam|telesync|ts|hdts)\b", "cam"),
]]
CODEC = [(re.compile(p, re.I), v) for p, v in [
    (r"\b(x265|h[ .]?265|hevc)\b", "x265"), (r"\b(x264|h[ .]?264|avc)\b", "x264"),
    (r"\bav1\b", "av1"), (r"\bxvid\b", "xvid"),
]]
HDR = re.compile(r"\b(hdr10\+?|hdr|dolby[ .]?vision|dv)\b", re.I)
AUDIO = re.compile(r"\b(atmos|truehd|dts-?hd|dts|dd[p+]?[ .]?5[ .]1|aac|ac3|eac3|flac)\b", re.I)

SEASON_EP = re.compile(
    r"[Ss](?P<s>\d{1,2})[ ._-]*(?:[Ee](?P<e1>\d{1,3})(?:[ ._-]*(?:-|[Ee])[ ._-]*[Ee]?(?P<e2>\d{1,3}))?)?"
)
ALT_EP = re.compile(r"\b(?P<s>\d{1,2})x(?P<e1>\d{2,3})\b")
SEASON_WORD = re.compile(r"\bSeason[ ._]?(?P<s>\d{1,2})\b", re.I)
DATE = re.compile(r"(?<![0-9])((?:19|20)\d{2})[ .\-_](0?[1-9]|1[0-2])[ .\-_](0?[1-9]|[12]\d|3[01])(?![0-9])")
ABSOLUTE = re.compile(r"(?:^|\s)-\s+(?:E|EP)?(?P<n>\d{1,4})(?:v\d)?(?=[\s\[(]|$)|\b(?:E|EP)(?P<n2>\d{2,4})(?:v\d)?(?=[\s\[(]|$)", re.I)
YEAR = re.compile(r"[\s(\[.]((?:19|20)\d{2})[\s)\].]")
JUNK = re.compile(
    r"\b(swedish|swesub|svenska|svensk|dubbad|textad|swe|nordic|dubbed|multi|complete|extended|unrated|remastered|internal|limited|proper|repack"
    r"|directors? cut|collection)\b|\[", re.I)
GROUP = re.compile(r"-([A-Za-z0-9]+)(?:\[[^\]]+\])?$")


@dataclass
class Release:
    raw: str
    title: str = ""
    year: int | None = None
    season: int | None = None
    episodes: list[int] = field(default_factory=list)
    season_pack: bool = False
    season_end: int | None = None  # set for multi-season packs (S01-S09)
    absolute: int | None = None  # anime style: "Show - 137" (no season)
    air_date: date | None = None  # daily / talk shows are named by date: Show.2026.11.10
    resolution: int | None = None
    source: str | None = None
    codec: str | None = None
    hdr: bool = False
    audio: str | None = None
    group: str | None = None
    proper: bool = False
    repack: bool = False

    @property
    def is_tv(self) -> bool:
        return self.season is not None or self.air_date is not None


def _first(patterns, text):
    for rx, val in patterns:
        if rx.search(text):
            return val
    return None


def parse(name: str) -> Release:
    r = Release(raw=name)
    base = re.sub(r"\.(mkv|mp4|avi|m4v|torrent)$", "", name.strip(), flags=re.I)
    text = _SEP.sub(" ", re.sub(r"^\s*\[[^\]]{1,40}\]\s*", "", base))   # leading [FansubGroup]

    r.resolution = _first(RESOLUTION, text)
    r.source = _first(SOURCE, text)
    r.codec = _first(CODEC, text)
    r.hdr = bool(HDR.search(text))
    m = AUDIO.search(text)
    r.audio = m.group(1).lower() if m else None
    r.proper = bool(re.search(r"\bproper\b", text, re.I))
    r.repack = bool(re.search(r"\b(repack|rerip)\b", text, re.I))
    g = GROUP.search(base.strip())
    r.group = g.group(1) if g and g.group(1).lower() not in {"dl", "rip", "ray", "hd"} else None

    cut = len(text)
    dm = None if SEASON_EP.search(text) else DATE.search(text)
    if dm:
        try:
            r.air_date = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
        except ValueError:
            dm = None
    m = None if dm else (SEASON_EP.search(text) or ALT_EP.search(text))
    if m:
        r.season = int(m.group("s"))
        e1 = m.group("e1")
        if e1:
            first = int(e1)
            e2 = m.groupdict().get("e2")
            last = int(e2) if e2 else first
            r.episodes = list(range(first, max(first, last) + 1))
        else:
            r.season_pack = True
            rng = re.match(r"[Ss]\d{1,2}(?:[ ._]*(?:-|to)[ ._]*[Ss]?|[ ._]+[Ss])(\d{1,2})\b", text[m.start():])
            if rng:
                r.season_end = int(rng.group(1))
        cut = m.start()
    else:
        m = SEASON_WORD.search(text)
        if m:
            r.season, r.season_pack, cut = int(m.group("s")), True, m.start()

    if dm:
        cut = dm.start()
    elif r.season is None:
        am = ABSOLUTE.search(text)
        if am:
            n = int(am.group("n") or am.group("n2"))
            if not (1900 <= n <= 2099 and am.group("n")):        # " - 2019" is a year, not episode 2019
                r.absolute, cut = n, am.start()
    tech = [x.start() for x in (
        *(rx.search(text) for rx, _ in RESOLUTION), *(rx.search(text) for rx, _ in SOURCE),
        *(rx.search(text) for rx, _ in CODEC), JUNK.search(text)) if x]
    limit = min([cut, *tech])

    years = [] if dm else [y for y in re.finditer(r"(?<![0-9])((?:19|20)\d{2})(?![0-9])", text) if 0 < y.start() < limit]
    if years:
        y = years[-1]
        r.year = int(y.group(1))
        limit = y.start()
    cut = limit

    r.title = re.sub(r"[\s(\[,.\-]+$", "", text[:cut]).strip()
    return r
