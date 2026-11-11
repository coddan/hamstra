"""Link albums that are already in the music folder to MusicBrainz (so the library shows what you own)."""
import json
import os
import re
import threading
from pathlib import Path

from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Album, Setting
from ..providers import musicbrainz
from . import music
from .music_parser import YEAR, name_matches

TRIED_KEY = "music_import_tried"
PLACEHOLDER = re.compile(r"^[^\w]*\w?[\W_]{6,}$")  # folders like "A------------" that only separate the alphabet
JOB: dict = {"running": False, "total": 0, "done": 0, "linked": 0, "result": None}


def split_name(name: str) -> tuple[str, str, int | None] | None:
    """(artist, album, year) from 'Artist-Album-CD-FLAC-2004-GRP' or 'Artist - Album (2004)'."""
    n = re.sub(r"_-_", " - ", name.strip())
    year = next(iter(reversed(YEAR.findall(n))), None)
    if " " in n:
        parts = [p.strip() for p in re.split(r"\s+-\s+", n)]
    else:
        parts = [p for p in n.split("-") if p]
    if len(parts) < 2:
        return None
    if " " in n and " " not in parts[1] and "-" in parts[1]:
        parts[1] = parts[1].split("-")[0]       # "Fate_of_Norns-Retail-2004-GRP": the rest is scene tags
    artist, album = (p.replace("_", " ").strip() for p in parts[:2])
    album = re.sub(r"[\(\[]?\b(19|20)\d{2}\b[\)\]]?", "", album).strip(" -")
    return (artist, album, int(year) if year else None) if artist and album else None


def _dirs(path: Path) -> list[Path]:
    try:
        with os.scandir(path) as it:
            return sorted((Path(e.path) for e in it if e.is_dir() and not e.name.startswith(("@", ".", "$"))), key=lambda p: p.name)
    except OSError:
        return []


def shallow_audio(folder: Path) -> bool:
    """Audio directly inside, or in a CD1/CD2 style subfolder."""
    try:
        with os.scandir(folder) as it:
            entries = list(it)
    except OSError:
        return False
    if any(e.is_file() and Path(e.name).suffix.lower() in music.AUDIO_EXT for e in entries):
        return True
    return any(e.is_dir() and re.match(r"(?i)^(cd|disc|disk)\s*\d+", e.name) and shallow_audio(Path(e.path)) for e in entries)


def candidates(root: Path, genre: str | None):
    """Yield (folder, genre_name, artist_hint) for every release folder to look at."""
    genres = [genre] if genre else ["", *music.genre_folders(root)]
    for g in genres:
        base = root / g if g else root
        for entry in _dirs(base):
            if not g and entry.name in music.genre_folders(root):
                continue                                   # a genre folder itself, handled in its own turn
            if PLACEHOLDER.match(entry.name):
                continue
            if shallow_audio(entry):
                yield entry, g, None
            else:                                           # Artist/Album layout
                for sub in _dirs(entry):
                    if shallow_audio(sub):
                        yield sub, g, entry.name


def _pick(folder_name: str, artist: str, album: str, year: int | None) -> dict | None:
    for c in musicbrainz.search_albums(f"{artist} {album}", limit=6):
        if not name_matches(folder_name, c["artist"], c["title"]):
            continue
        if year and c["year"] and abs(c["year"] - year) > 5:
            continue
        return c
    return None


def run(db: Session, progress: dict, genre: str | None = None, retry: bool = False) -> dict:
    root = music.music_root(db)
    if not root:
        return {"error": "no music folder"}
    rootp = Path(root.path)
    row = db.get(Setting, TRIED_KEY)
    tried: set[str] = set(json.loads(row.value)) if row else set()
    known = {p for (p,) in db.query(Album.path).filter(Album.path.isnot(None))}
    todo = [t for t in candidates(rootp, genre) if str(t[0]) not in known and (retry or str(t[0]) not in tried)]
    progress.update(total=len(todo), done=0, linked=0)
    out = {"linked": 0, "not_found": 0, "errors": 0}
    for folder, g, artist_hint in todo:
        try:
            parsed = split_name(f"{artist_hint} - {folder.name}" if artist_hint else folder.name)
            hit = _pick(folder.name if not artist_hint else f"{artist_hint} {folder.name}", *parsed) if parsed else None
            if hit and not db.query(Album).filter_by(mbid=hit["mbid"]).first():
                db.add(Album(**hit, monitored=False, has_files=True, path=str(folder), genre=g, root_folder_id=root.id))
                db.commit()
                out["linked"] += 1
                progress["linked"] += 1
            elif not hit:
                out["not_found"] += 1
            tried.add(str(folder))
        except Exception:
            db.rollback()
            out["errors"] += 1
        progress["done"] += 1
        if progress["done"] % 25 == 0:  # keep what we have learned if the container restarts mid-way
            _save_tried(db, tried)
    _save_tried(db, tried)
    return out


def _save_tried(db: Session, tried: set[str]) -> None:
    val = json.dumps(sorted(tried))
    row = db.get(Setting, TRIED_KEY)
    if row:
        row.value = val
    else:
        db.add(Setting(key=TRIED_KEY, value=val))
    db.commit()


def start(genre: str | None = None, retry: bool = False) -> dict:
    if JOB["running"]:
        return JOB

    def work():
        with SessionLocal() as db:
            try:
                JOB["result"] = run(db, JOB, genre or None, retry)
            except Exception as e:
                JOB["result"] = {"error": str(e)}
            finally:
                JOB["running"] = False

    JOB.update(running=True, total=0, done=0, linked=0, result=None)
    threading.Thread(target=work, daemon=True).start()
    return JOB
