import re
from dataclasses import dataclass

from . import naming

FORMATS = [("flac", r"\bflac\b"), ("alac", r"\balac\b"), ("mp3", r"\bmp3\b"), ("aac", r"\b(aac|m4a)\b"),
           ("ogg", r"\b(ogg|opus)\b"), ("wav", r"\bwav\b")]
BITRATES = [("320", r"\b320\b"), ("v0", r"\bv0\b"), ("v1", r"\bv1\b"), ("v2", r"\bv2\b"), ("256", r"\b256\b"),
            ("192", r"\b192\b"), ("128", r"\b128\b")]
SOURCES = [("vinyl", r"\b(vinyl|lp|vinylrip|vls)\b"), ("sacd", r"\bsacd\b"), ("cassette", r"\b(cassette|tape)\b"),
           ("web", r"\bweb\b"), ("cd", r"\b(cd|cdda|cdr|cdrip|cdflac)\b"), ("dvd", r"\bdvd[a-z]?\b")]
BITS24 = re.compile(r"\b24[ -]?bit\b|\b24[ -](44|48|88|96|192)\b", re.I)
YEAR = re.compile(r"(?<![0-9])((?:19|20)\d{2})(?![0-9])")
STOP = {"the", "a", "an", "and", "of", "feat", "ft"}


@dataclass
class MusicRelease:
    raw: str
    format: str | None = None
    bitrate: str | None = None
    bits24: bool = False
    source: str | None = None
    year: int | None = None


def _text(name: str) -> str:
    return re.sub(r"[._\-\[\]()]+", " ", re.sub(r"\.(torrent|zip|rar)$", "", name.strip(), flags=re.I))


def parse_music(name: str) -> MusicRelease:
    t = _text(name)
    low = t.lower()
    r = MusicRelease(raw=name)
    r.format = next((v for v, rx in FORMATS if re.search(rx, low)), None)
    r.bitrate = next((v for v, rx in BITRATES if re.search(rx, low)), None)
    r.bits24 = bool(BITS24.search(t))
    r.source = next((v for v, rx in SOURCES if re.search(rx, low)), None)
    years = YEAR.findall(t)
    r.year = int(years[-1]) if years else None
    return r


def quality_key(rel: MusicRelease, category: str = "") -> str | None:
    """flac | flac-24 | mp3-320 | mp3-v0 | mp3-v2 | mp3-256 | ... | aac | None (unknown)."""
    fmt, bitrate = rel.format, rel.bitrate
    cat = (category or "").lower()
    if fmt is None and "flac" in cat:
        fmt = "flac"
        rel = MusicRelease(raw=rel.raw, format="flac", bits24="24" in cat or rel.bits24)
    elif fmt is None and "mp3" in cat:
        fmt = "mp3"
        m = re.search(r"\b(320|v0|v1|v2|256|192|128)\b", cat)
        bitrate = bitrate or (m.group(1) if m else None)
    if fmt in ("flac", "alac", "wav"):
        return "flac-24" if rel.bits24 else "flac"
    if fmt == "mp3":
        return f"mp3-{bitrate}" if bitrate else "mp3-unknown"
    if fmt in ("aac", "ogg"):
        return "aac"
    return None


def tokens(text: str) -> list[str]:
    t = naming.normalize(text.replace("&", " and "))
    return [w for w in t.split() if w]


def name_matches(release_title: str, artist: str, album: str) -> bool:
    """Every word of the artist and of the album appears in the release name (names are written very differently)."""
    have = set(tokens(_text(release_title)))
    have |= {t[:-1] for t in have if len(t) > 3 and t.endswith("s")}  # possessives: "Floyd's" -> "floyd"
    a = [w for w in tokens(artist) if w not in STOP] or tokens(artist)
    b = [w for w in tokens(album) if w not in STOP] or tokens(album)
    return bool(a) and bool(b) and set(a) <= have and set(b) <= have
