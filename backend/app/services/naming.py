import re
import unicodedata

VIDEO_EXT = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".wmv"}
_ILLEGAL = re.compile(r'[<>:"/\\|?*]')


def clean(name: str) -> str:
    return _ILLEGAL.sub("", name).strip().rstrip(".")


def folder_name(title: str, year: int | None) -> str:
    return clean(f"{title} ({year})") if year else clean(title)


_ROMAN = {"ii": "2", "iii": "3", "iv": "4", "vi": "6", "vii": "7", "viii": "8", "ix": "9"}


def normalize(title: str) -> str:
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"['\u2019`]", "", t)  # "Daddy's" and "Daddys" are the same title
    words = re.sub(r"[^a-z0-9]+", " ", t).split()
    if len(words) > 1 and words[0] == "the":
        words = words[1:]  # "The Simpsons" == "Simpsons"
    return " ".join(_ROMAN.get(w, w) if i > 0 else w for i, w in enumerate(words))  # "Dundee II" == "Dundee 2"


def parse_folder(name: str) -> tuple[str, int | None]:
    m = re.match(r"^(.*?)\s*\((\d{4})\)\s*$", name)
    return (m.group(1), int(m.group(2))) if m else (name, None)


_EP = re.compile(r"[Ss](\d{1,2})[ ._-]*[Ee](\d{1,3})(?:[ ._-]*[Ee-](\d{1,3}))?|(\d{1,2})x(\d{2,3})")


def parse_episode(filename: str) -> list[tuple[int, int]]:
    m = _EP.search(filename)
    if not m:
        return []
    if m.group(4):
        return [(int(m.group(4)), int(m.group(5)))]
    s, first = int(m.group(1)), int(m.group(2))
    last = int(m.group(3)) if m.group(3) else first
    return [(s, e) for e in range(first, max(first, last) + 1)]


_IMDB = re.compile(r"\b(tt\d{6,10})\b", re.I)


def imdb_id_in(text: str) -> str | None:
    """Return an IMDb ID found in plain text or an imdb.com URL."""
    m = _IMDB.search(text)
    return m.group(1).lower() if m else None


def parse_air_date(filename: str):
    """Air date in a file name such as 'Show.2026.11.10.720p.mkv', or None."""
    from .parser import parse

    return parse(filename).air_date
