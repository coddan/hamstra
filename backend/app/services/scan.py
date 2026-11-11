import json
import os
import re
import threading
from pathlib import Path

from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Movie, RootFolder, Series, Setting
from . import naming
from .parser import parse

IGNORED = ("@", ".", "$")
SKIP_DIRS = {"subs", "subtitles", "sub", "sample", "samples", "extras", "featurettes", "artwork", "covers", "cover", "screens", "proof", "scans"}
IGNORE_KEY = "ignored_paths"
DUP_KEY = "duplicate_folders"
GUESS_KEY = "guessed_matches"
_COUNTRY = re.compile(r"\s*\((?:US|UK|AU|CA|NZ)\)$", re.I)


def _videos(folder: Path):
    if folder.is_file():
        if folder.suffix.lower() in naming.VIDEO_EXT:
            yield folder
        return
    for p in folder.rglob("*"):
        if p.is_file() and p.suffix.lower() in naming.VIDEO_EXT and not any(
                part.startswith(IGNORED) for part in p.relative_to(folder).parts):
            yield p


DIR_FLAGS: dict[str, bool] = {}  # filled by entries(): directory type comes with the listing, no extra network round trip


def is_dir(p: Path) -> bool:
    flag = DIR_FLAGS.get(str(p))
    return p.is_dir() if flag is None else flag


def _listing(path: Path) -> list[tuple[Path, bool]]:
    out = []
    with os.scandir(path) as it:
        for e in it:
            try:
                d = e.is_dir()          # uses the type returned by the directory listing itself
            except OSError:
                d = False
            out.append((Path(e.path), d))
    out.sort(key=lambda t: t[0].name)
    return out


def _wanted(p: Path, d: bool) -> bool:
    return not p.name.startswith(IGNORED) and (d or p.suffix.lower() in naming.VIDEO_EXT)


def entries(base: Path, collections: set[str] | None = None) -> list[Path]:
    collections = collections or set()
    out: list[Path] = []
    for p, d in _listing(base):
        if not _wanted(p, d):
            continue
        DIR_FLAGS[str(p)] = d
        if str(p) in collections and d:  # a folder holding several films: each film is its own entry
            for c, cd in _listing(p):
                if _wanted(c, cd) and c.name.lower() not in SKIP_DIRS and (
                        c.suffix.lower() in naming.VIDEO_EXT or (cd and any(True for _ in _videos(c)))):
                    DIR_FLAGS[str(c)] = cd
                    out.append(c)
        else:
            out.append(p)
    return out


def folder_title(entry: Path) -> tuple[str, int | None]:
    r = parse(entry.stem if entry.suffix.lower() in naming.VIDEO_EXT else entry.name)
    return _COUNTRY.sub("", r.title), r.year


COLLECTIONS_KEY = "collection_folders"
_SERIES_NAME = re.compile(r"(\bS\d{1,2}([ ._-]*E\d{1,3})?\b|\bseason\b|s[äa]song|\bavsnitt\b|\bcomplete[ ._]series\b|\bE\d{2,3}\b|\d{1,2}x\d{2})", re.I)


def get_collections(db: Session) -> set[str]:
    row = db.get(Setting, COLLECTIONS_KEY)
    return set(json.loads(row.value)) if row else set()


def set_collections(db: Session, paths: set[str]) -> None:
    row = db.get(Setting, COLLECTIONS_KEY)
    if row:
        row.value = json.dumps(sorted(paths))
    else:
        db.add(Setting(key=COLLECTIONS_KEY, value=json.dumps(sorted(paths))))
    db.commit()


def video_files(folder: Path, limit: int = 400) -> list[Path]:
    out = []
    for p in _videos(folder):
        out.append(p)
        if len(out) >= limit:
            break
    return out


def looks_like(entry: Path, deep: bool = True) -> str:
    """'series', 'collection' (several different films in one folder) or 'movie'."""
    name = entry.stem if entry.suffix.lower() in naming.VIDEO_EXT else entry.name
    if _SERIES_NAME.search(name):
        return "series"
    if deep and is_dir(entry):
        vids = video_files(entry)
        if len(vids) >= 2 and sum(1 for v in vids if naming.parse_episode(v.name)) >= max(2, len(vids) // 2):
            return "series"
        # several different films: most files carry their own year ("Pippi.1969.mkv"); episodes of a show do not
        parsed = [parse(v.stem) for v in vids]
        titles = {naming.normalize(r.title) for r in parsed}
        titles.discard("")
        if len(vids) >= 3 and len(titles) >= 3 and sum(1 for r in parsed if r.year) >= 0.6 * len(vids):
            return "collection"
    return "movie"


def _keys(title: str) -> set[str]:
    return {naming.normalize(title), naming.normalize(_COUNTRY.sub("", title))}


def build_index(items) -> dict[str, list]:
    idx: dict[str, list] = {}
    for it in items:
        for k in _keys(it.title):
            idx.setdefault(k, []).append(it)
    return idx


def lookup(idx: dict[str, list], title: str, year: int | None):
    """Item with the same (normalised) title and a compatible year; O(1) instead of scanning the library."""
    for it in idx.get(naming.normalize(title), []):
        if year is None or it.year in (None, year):
            return it
    return None


def get_guessed(db: Session) -> dict[str, dict]:
    row = db.get(Setting, GUESS_KEY)
    return json.loads(row.value) if row else {}


def set_guessed(db: Session, data: dict[str, dict]) -> None:
    row = db.get(Setting, GUESS_KEY)
    if row:
        row.value = json.dumps(data)
    else:
        db.add(Setting(key=GUESS_KEY, value=json.dumps(data)))
    db.commit()


def get_duplicates(db: Session) -> dict[str, str]:
    row = db.get(Setting, DUP_KEY)
    return json.loads(row.value) if row else {}


def get_ignored(db: Session) -> set[str]:
    row = db.get(Setting, IGNORE_KEY)
    return set(json.loads(row.value)) if row else set()


def set_ignored(db: Session, paths: set[str]) -> None:
    row = db.get(Setting, IGNORE_KEY)
    if row:
        row.value = json.dumps(sorted(paths))
    else:
        db.add(Setting(key=IGNORE_KEY, value=json.dumps(sorted(paths))))
    db.commit()


def scan(db: Session, light: bool = False) -> dict:
    """light=True only lists top-level names to find unmatched entries (no disk reads of file contents)."""
    result = {"movies_matched": 0, "episodes_matched": 0, "unmatched": []}
    ignored = get_ignored(db)
    collections = get_collections(db)
    movies, series = db.query(Movie).all(), db.query(Series).all()
    movie_by_path = {m.path: m for m in movies if m.path}
    movie_idx, series_idx = build_index(movies), build_index(series)
    series_by_path = {x.path: x for x in series if x.path}

    for root in db.query(RootFolder).all():
        base = Path(root.path)
        if root.kind == "music" or not base.is_dir():
            continue  # music has its own library
        for entry in entries(base, collections):
            if str(entry) in ignored:
                continue
            title, year = folder_title(entry)
            if not title:
                continue
            known_series = series_by_path.get(str(entry))
            is_series = root.kind == "tv" or (root.kind == "mixed" and looks_like(entry, deep=False) == "series")
            if known_series or is_series:
                s = known_series or lookup(series_idx, title, year)
                if not s:
                    result["unmatched"].append({"kind": "tv", "path": str(entry), "root_kind": root.kind})
                    continue
                s.path = str(entry)
                if light:
                    continue
                by_ep = {(e.season, e.number): e for e in s.episodes}
                for f in _videos(entry):
                    for key in naming.parse_episode(f.name):
                        e = by_ep.get(key)
                        if e and e.file_path != str(f):
                            e.file_path = str(f)
                            e.file_resolution = parse(f.name).resolution
                            result["episodes_matched"] += 1
            else:
                m = movie_by_path.get(str(entry)) or lookup(movie_idx, title, year)
                if not m:
                    result["unmatched"].append({"kind": "movie", "path": str(entry), "root_kind": root.kind})
                    continue
                m.path = str(entry)
                m.root_folder_id = root.id
                if light:
                    result["movies_matched"] += 1
                    continue
                vids = list(_videos(entry))
                m.has_file = bool(vids)
                if vids:
                    m.file_resolution = parse(max(vids, key=lambda p: p.stat().st_size).name).resolution or m.file_resolution
                result["movies_matched"] += 1
    db.commit()
    return result


def root_for(entry: Path, roots: dict[str, RootFolder]) -> RootFolder | None:
    for parent in entry.parents:
        if str(parent) in roots:
            return roots[str(parent)]
    return None


def import_unmatched(db: Session, progress: dict | None = None, guess: bool = False) -> dict:
    """Work out what each unmatched folder is (series / movie / collection of films) and link it. DB only; no files change."""
    from ..api.series import add_series_from_provider
    from ..providers import tmdb
    from . import matching

    out = {"added": [], "failed": [], "collections": [], "guessed": 0}
    dups: dict[str, str] = {}
    guessed = get_guessed(db)
    roots = {r.path: r for r in db.query(RootFolder).all()}
    tv_root = next((r for r in roots.values() if r.kind == "tv"), None)
    done = 0

    for round_ in range(2):  # round 2 handles the films inside folders that round 1 recognised as collections
        todo = scan(db)["unmatched"]
        if round_ == 1:  # second round: only the files inside folders that were just recognised as collections
            cols = get_collections(db)
            todo = [i for i in todo if str(Path(i["path"]).parent) in cols]
        if progress is not None:
            progress.update(total=done + len(todo), done=done)
        new_collections = False
        for item in todo:
            entry = Path(item["path"])
            title, year = folder_title(entry)
            folder_guess = "movie" if round_ == 1 else looks_like(entry)
            if item["kind"] == "tv":
                folder_guess = "series"  # the TV folder only holds series
            try:
                if folder_guess == "collection":
                    cols = get_collections(db)
                    cols.add(str(entry))
                    set_collections(db, cols)
                    out["collections"].append(str(entry))
                    new_collections = True
                    continue
                # the folder's configured type decides: a series folder holds series, a movie folder holds movies
                kind = "series" if item["kind"] == "tv" else "movie"
                if kind == "movie" and item.get("root_kind") != "mixed" and looks_like(entry, deep=False) == "series":
                    raise LookupError("looks like a series but sits in a movies folder")  # a human decides
                hit = matching.match_show(title, year) if kind == "series" else matching.match_movie(title, year)
                score = None
                if not hit and guess:
                    g = matching.guess_show(title, year) if kind == "series" else matching.guess_movie(title, year)
                    if g:
                        hit, score = g
                if not hit:
                    raise LookupError("no match")
                root = root_for(entry, roots)
                if kind == "series":
                    have = db.query(Series).filter_by(tvmaze_id=hit["tvmaze_id"]).first()
                    if have:
                        dups[str(entry)] = have.path or have.title
                        raise LookupError("already in library (another folder)")
                    sr = add_series_from_provider(db, hit["tvmaze_id"])
                    sr.path, sr.monitored = str(entry), False  # opt in per series; avoids mass-downloading old episodes
                    if score is not None:
                        guessed[str(entry)] = {"kind": "series", "id": hit["tvmaze_id"], "score": round(score, 2)}
                    if tv_root:
                        sr.root_folder_id = tv_root.id
                    for e in sr.episodes:
                        e.monitored = False
                    db.commit()
                else:
                    have = db.query(Movie).filter_by(tmdb_id=hit["tmdb_id"]).first()
                    if have:
                        dups[str(entry)] = have.path or have.title
                        raise LookupError("already in library (another folder)")
                    d = tmdb.movie_details(hit["tmdb_id"])
                    db.add(Movie(
                        tmdb_id=d["tmdb_id"], title=d["title"], year=d["year"], overview=d["overview"],
                        poster_url=d["poster_url"], certification=d["certification"], imdb_id=d.get("imdb_id"),
                        release_date=None, root_folder_id=root.id if root else None, path=str(entry),
                    ))
                    if score is not None:
                        guessed[str(entry)] = {"kind": "movie", "id": hit["tmdb_id"], "score": round(score, 2)}
                    db.commit()
                out["added"].append(str(entry))
            except Exception as e:
                db.rollback()
                out["failed"].append({"path": str(entry), "reason": str(e)})
            done += 1
            if progress is not None:
                progress["done"] = done
        if not new_collections:
            break

    set_guessed(db, guessed)
    out["guessed"] = sum(1 for p in out["added"] if p in guessed)
    row = db.get(Setting, DUP_KEY)
    known = json.loads(row.value) if row else {}
    known.update(dups)
    if row:
        row.value = json.dumps(known)
    else:
        db.add(Setting(key=DUP_KEY, value=json.dumps(known)))
    db.commit()
    out["scan"] = scan(db)
    return out


JOB: dict = {"running": False, "total": 0, "done": 0, "result": None}


def start_import_job(guess: bool = False) -> dict:
    if JOB["running"]:
        return JOB

    def run():
        with SessionLocal() as db:
            try:
                JOB["result"] = import_unmatched(db, JOB, guess)
            except Exception as e:
                JOB["result"] = {"error": str(e)}
            finally:
                JOB["running"] = False

    JOB.update(running=True, total=0, done=0, result=None)
    threading.Thread(target=run, daemon=True).start()
    return JOB
