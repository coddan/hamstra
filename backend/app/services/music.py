import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from ..indexers.torznab import Result
from ..models import Album, RootFolder, Setting
from . import naming
from .music_parser import STOP, name_matches, parse_music, quality_key, tokens

STOP_NAMES = STOP

AUDIO_EXT = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".ape", ".wv", ".alac"}
KEEP_EXT = AUDIO_EXT | {".jpg", ".jpeg", ".png", ".cue", ".log", ".pdf"}  # copied along with the music
SKIP_DIRS = {"proof", "sample", "samples"}
KEY = "music"
ALL_QUALITIES = ["flac-24", "flac", "mp3-320", "mp3-v0", "mp3-v1", "mp3-v2", "mp3-256", "mp3-192", "mp3-128", "mp3-unknown", "aac"]
DEFAULTS = {
    "allowed": ["flac", "flac-24", "mp3-320", "mp3-v0", "mp3-v2"],
    "order": ["flac", "flac-24", "mp3-320", "mp3-v0", "mp3-v1", "mp3-v2", "mp3-256", "mp3-192", "mp3-128", "mp3-unknown", "aac"],
    "min_seeders": 1, "max_size_mb": 3000,
    "reject_words": "live,demos,karaoke,tribute,instrumental,acoustic,remixes,covers,bootleg",
    "prefer_words": "",
    "layout": "release",  # release: <genre>/<release folder name> (scene style)   artist: <genre>/<Artist>/<Album (Year)>
}


def get_profile(db: Session) -> dict:
    row = db.get(Setting, KEY)
    return {**DEFAULTS, **(json.loads(row.value) if row else {})}


def save_profile(db: Session, data: dict) -> dict:
    merged = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    row = db.get(Setting, KEY)
    if row:
        row.value = json.dumps(merged)
    else:
        db.add(Setting(key=KEY, value=json.dumps(merged)))
    db.commit()
    return merged


def _words(text: str) -> list[str]:
    return [w.strip().lower() for w in (text or "").split(",") if w.strip()]


@dataclass
class Decision:
    result: Result
    accepted: bool
    reasons: list[str]
    quality: str | None
    score: float = 0.0


def evaluate(r: Result, album: Album, profile: dict, blocked: set[str] = frozenset()) -> Decision:
    rel = parse_music(r.title)
    q = quality_key(rel, r.category)
    why: list[str] = []
    if (r.info_hash and r.info_hash in blocked) or r.title in blocked:
        why.append("blocklisted")
    if not name_matches(r.title, album.artist, album.title):
        why.append("not this artist/album")
    if q is None:
        why.append("unknown audio format")
    elif q not in profile["allowed"]:
        why.append(f"{q} not allowed")
    have, album_words = set(tokens(r.title)), set(tokens(album.title)) | set(tokens(album.artist))
    for w in _words(profile["reject_words"]):
        if w in have and w not in album_words:
            why.append(f"contains '{w}'")
            break
    if r.size and r.size > profile["max_size_mb"] * 1e6:
        why.append("too large")
    if r.seeders < profile["min_seeders"]:
        why.append("not enough seeders")

    order = profile["order"]
    score = (len(order) - order.index(q)) * 10 if q in order else 0
    score += 20 * sum(1 for w in _words(profile["prefer_words"]) if w in have)
    if rel.source == "cd":
        score += 3
    score += min(r.seeders, 100) / 5 + (50 - min(max(r.priority, 1), 50)) * 0.2
    return Decision(r, not why, why, q, score)


def best(results: list[Result], album: Album, profile: dict, blocked: set[str] = frozenset()) -> Decision | None:
    ok = [d for d in (evaluate(r, album, profile, blocked) for r in results) if d.accepted]
    return max(ok, key=lambda d: d.score) if ok else None


# ---------- library folders ----------
def music_root(db: Session) -> RootFolder | None:
    return db.query(RootFolder).filter_by(kind="music").first()


def genre_folders(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    out = []
    with os.scandir(root) as it:
        for e in it:
            if e.is_dir() and not e.name.startswith(("@", ".", "$")):
                out.append(e.name)
    return sorted(out, key=str.lower)


def clean_name(text: str) -> str:
    return naming.clean(text) or "Unknown"


def _listdir(path: Path) -> list[Path]:
    try:
        with os.scandir(path) as it:
            return [Path(e.path) for e in it if e.is_dir() and not e.name.startswith(("@", ".", "$"))]
    except OSError:
        return []


def _entries(path: Path) -> list[str]:
    try:
        with os.scandir(path) as it:
            return [e.name for e in it if e.is_dir() and not e.name.startswith(("@", ".", "$"))]
    except OSError:
        return []


def _folders(root: Path) -> list[Path]:
    return [root, *(root / n for n in genre_folders(root))]


def find_artist_dir(root: Path, artist: str, budget: float = 15.0) -> Path | None:
    """Existing folder named exactly like the artist (Artist/Album layout)."""
    key, start = naming.normalize(artist), time.monotonic()
    for genre in _folders(root):
        for n in _entries(genre):
            if naming.normalize(n) == key:
                return genre / n
        if time.monotonic() - start > budget:
            break
    return None


def find_artist_genre(root: Path, artist: str, budget: float = 15.0) -> str | None:
    """Genre folder where this artist's releases already live (works for scene-named release folders too)."""
    a, start = [w for w in tokens(artist) if w not in STOP_NAMES] or tokens(artist), time.monotonic()
    if not a:
        return None
    for genre in genre_folders(root):
        for n in _entries(root / genre):
            if tokens(re.sub(r"[._\-]+", " ", n))[: len(a)] == a or naming.normalize(n) == naming.normalize(artist):
                return genre
        if time.monotonic() - start > budget:
            break
    return None


def find_existing_album(root: Path, artist: str, title: str, budget: float = 20.0) -> Path | None:
    """An album that is already in the music folder: a scene-named release folder, or Artist/Album folders."""
    start = time.monotonic()
    for genre in _folders(root):
        for n in _entries(genre):
            if name_matches(n, artist, title):
                return genre / n
            if naming.normalize(n) == naming.normalize(artist):           # Artist/Album layout: look one level down
                for sub in _entries(genre / n):
                    if name_matches(sub, artist, title) or naming.normalize(sub).startswith(naming.normalize(title)):
                        return genre / n / sub
        if time.monotonic() - start > budget:
            break
    return None


def has_audio(folder: Path) -> bool:
    return any(p.suffix.lower() in AUDIO_EXT for p in folder.rglob("*") if p.is_file())


def target_folder(db: Session, album: Album) -> tuple[Path | None, str]:
    """Where a new album goes. Returns (final folder, genre); the folder is None for the release layout
    because it is only known once the download exists (it keeps the release's own folder name)."""
    root = music_root(db)
    if not root:
        raise ValueError("No music folder configured")
    rootp, genre = Path(root.path), album.genre or ""
    layout = get_profile(db).get("layout", "release")
    if not genre:
        if layout == "artist":
            found = find_artist_dir(rootp, album.artist)
            genre = "" if not found or found.parent == rootp else found.parent.name
        else:
            genre = find_artist_genre(rootp, album.artist) or ""
    if layout == "release":
        return None, genre
    base = rootp / genre if genre else rootp
    year = f" ({album.year})" if album.year else ""
    return base / clean_name(album.artist) / f"{clean_name(album.title)}{year}", genre


def locate(db: Session, album: Album) -> None:
    """Fill path/genre/has_files for an album, detecting a copy that is already in the library."""
    root = music_root(db)
    if not root:
        return
    existing = find_existing_album(Path(root.path), album.artist, album.title)
    album.root_folder_id = root.id
    if existing:
        album.path, album.has_files = str(existing), has_audio(existing)
        parts = existing.relative_to(root.path).parts
        album.genre = parts[0] if len(parts) > 1 else ""
        return
    path, album.genre = target_folder(db, album)
    album.path = str(path) if path else None


def enrich(results: list[Result], album: Album, limit: int = 6) -> None:
    """archive.org titles rarely state the audio format: look inside the few items whose name matches this album."""
    from ..indexers import archiveorg

    done = 0
    for r in results:
        if done >= limit:
            break
        if r.category in ("audio", "etree") and r.guid and name_matches(r.title, album.artist, album.title) \
                and quality_key(parse_music(r.title), r.category) is None:
            hint = archiveorg.audio_quality_hint(r.guid)
            done += 1
            if hint:
                r.category = hint
