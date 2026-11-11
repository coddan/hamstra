from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Movie, RootFolder, Series
from ..services import scan as scan_service

router = APIRouter(prefix="/api/v1/library", tags=["library"])


@router.post("/scan")
def scan(db: Session = Depends(get_db)):
    return scan_service.scan(db)


@router.post("/import")
def import_unmatched(guess: bool = False):
    """Auto-match every unmatched folder. guess=true also accepts best guesses (listed under 'Best guesses' for review)."""
    return scan_service.start_import_job(guess)


@router.get("/import")
def import_status():
    return scan_service.JOB


@router.get("/unmatched")
def unmatched(db: Session = Depends(get_db)):
    """Folders in the media roots that are not in the library yet (fast: only reads top-level names)."""
    res = scan_service.scan(db, light=True)
    out = []
    dups = scan_service.get_duplicates(db)
    for u in res["unmatched"]:
        entry = Path(u["path"])
        title, year = scan_service.folder_title(entry)
        out.append({**u, "name": entry.name, "title": title, "year": year, "is_dir": scan_service.is_dir(entry),
                    "guess": scan_service.looks_like(entry, deep=False) if u["kind"] != "tv" else "series", "videos": None,
                    "mismatch": u["kind"] == "movie" and u.get("root_kind") != "mixed" and scan_service.looks_like(entry, deep=False) == "series",
                    "root": str(entry.parent), "duplicate_of": dups.get(u["path"])})
    return {"items": out, "ignored": len(scan_service.get_ignored(db)),
            "collections": sorted(scan_service.get_collections(db))}


@router.get("/inspect")
def inspect(path: str, db: Session = Depends(get_db)):
    """What is inside one folder (read only when you open it): kind guess and number of video files."""
    entry = Path(path)
    if not entry.exists():
        raise HTTPException(404, "Folder not found")
    vids = scan_service.video_files(entry, 200) if entry.is_dir() else [entry]
    root = scan_service.root_for(entry, {r.path: r for r in db.query(RootFolder).all()})
    guess = "series" if root and root.kind == "tv" else scan_service.looks_like(entry)  # the TV folder only holds series
    return {"guess": guess, "videos": len(vids), "files": [v.name for v in vids[:8]]}


class MatchIn(BaseModel):
    path: str
    kind: str  # movie | tv
    tmdb_id: int | None = None
    tvmaze_id: int | None = None


@router.post("/match", status_code=201)
def match(body: MatchIn, db: Session = Depends(get_db)):
    from ..api.series import add_series_from_provider
    from ..providers import tmdb

    entry = Path(body.path)
    roots = {r.path: r for r in db.query(RootFolder).all()}
    root = scan_service.root_for(entry, roots)
    if not root or not entry.exists():
        raise HTTPException(400, "Path is not a folder or file inside a library root")
    if body.kind == "movie":
        if not body.tmdb_id:
            raise HTTPException(400, "tmdb_id required")
        have = db.query(Movie).filter_by(tmdb_id=body.tmdb_id).first()
        if have:
            raise HTTPException(409, f"Already in the library at {have.path}")
        d = tmdb.movie_details(body.tmdb_id)
        movie = Movie(tmdb_id=d["tmdb_id"], title=d["title"], year=d["year"], overview=d["overview"],
                      poster_url=d["poster_url"], certification=d["certification"], imdb_id=d.get("imdb_id"),
                      root_folder_id=root.id, path=str(entry))
        db.add(movie)
        db.commit()
    else:
        if not body.tvmaze_id:
            raise HTTPException(400, "tvmaze_id required")
        have = db.query(Series).filter_by(tvmaze_id=body.tvmaze_id).first()
        if have:
            raise HTTPException(409, f"Already in the library at {have.path}")
        s = add_series_from_provider(db, body.tvmaze_id)
        tv = next((r for r in roots.values() if r.kind == "tv"), None)
        s.path, s.monitored = str(entry), False
        if tv:
            s.root_folder_id = tv.id
        for e in s.episodes:
            e.monitored = False
        db.commit()
    scan_service.scan(db)
    if body.kind == "movie":
        movie = db.query(Movie).filter_by(tmdb_id=body.tmdb_id).first()
        return {"ok": True, "title": movie.title, "year": movie.year, "has_file": bool(movie.has_file)}
    s = db.query(Series).filter_by(tvmaze_id=body.tvmaze_id).first()
    return {"ok": True, "title": s.title, "year": s.year, "episodes": len(s.episodes),
            "files_found": sum(1 for e in s.episodes if e.file_path)}


class PathIn(BaseModel):
    path: str


@router.post("/ignore")
def ignore(body: PathIn, db: Session = Depends(get_db)):
    paths = scan_service.get_ignored(db)
    paths.add(body.path)
    scan_service.set_ignored(db, paths)
    return {"ignored": len(paths)}


@router.get("/ignored")
def ignored(db: Session = Depends(get_db)):
    return sorted(scan_service.get_ignored(db))


@router.post("/unignore")
def unignore(body: PathIn, db: Session = Depends(get_db)):
    paths = scan_service.get_ignored(db)
    paths.discard(body.path)
    scan_service.set_ignored(db, paths)
    return {"ignored": len(paths)}


@router.post("/ignore-duplicates")
def ignore_duplicates(db: Session = Depends(get_db)):
    """Ignore every folder that is a second copy of something already in the library."""
    dups = scan_service.get_duplicates(db)
    res = scan_service.scan(db)
    paths = scan_service.get_ignored(db)
    n = 0
    for u in res["unmatched"]:
        if u["path"] in dups:
            paths.add(u["path"])
            n += 1
    scan_service.set_ignored(db, paths)
    return {"ignored": n}


class ListImport(BaseModel):
    list: str  # TMDB list id or URL, or a trakt.tv list/chart URL
    search_now: bool = False


def _add_entries(db: Session, entries: list[dict], search_now: bool) -> dict:
    """entries: {type: movie|tv, label, tmdb_id?, tmdb_tv_id?, imdb?}"""
    from ..api import movies as movies_api, series as series_api
    from ..providers import tmdb, tvmaze

    res = {"added": [], "skipped": [], "failed": []}
    for it in entries:
        label = it["label"]
        try:
            if it["type"] == "movie":
                if not it.get("tmdb_id"):
                    raise LookupError("no TMDB id")
                if db.query(Movie).filter_by(tmdb_id=it["tmdb_id"]).first():
                    res["skipped"].append(label)
                    continue
                movies_api.add_movie(movies_api.MovieAdd(tmdb_id=it["tmdb_id"], search_now=search_now), db)
            else:
                imdb = it.get("imdb") or (tmdb.tv_imdb_id(it["tmdb_tv_id"]) if it.get("tmdb_tv_id") else None)
                hits = tvmaze.lookup_imdb(imdb) if imdb else []
                if not hits:
                    raise LookupError("not found on TVmaze")
                if db.query(Series).filter_by(tvmaze_id=hits[0]["tvmaze_id"]).first():
                    res["skipped"].append(label)
                    continue
                series_api.add_series(series_api.SeriesAdd(tvmaze_id=hits[0]["tvmaze_id"], search_now=search_now), db)
            res["added"].append(label)
        except Exception as e:
            db.rollback()
            res["failed"].append({"item": label, "reason": getattr(e, "detail", str(e))})
    return res


@router.post("/collection")
def mark_collection(body: PathIn, db: Session = Depends(get_db)):
    """Treat a folder as a collection: each film/episode file inside becomes its own entry."""
    p = Path(body.path)
    if not p.is_dir():
        raise HTTPException(400, "Not a folder")
    cols = scan_service.get_collections(db)
    cols.add(body.path)
    scan_service.set_collections(db, cols)
    return {"collections": len(cols)}


@router.post("/uncollection")
def unmark_collection(body: PathIn, db: Session = Depends(get_db)):
    cols = scan_service.get_collections(db)
    cols.discard(body.path)
    scan_service.set_collections(db, cols)
    return {"collections": len(cols)}


@router.post("/import-list")
def import_list(body: ListImport, db: Session = Depends(get_db)):
    """Add everything from a public TMDB or Trakt list that is not in the library yet."""
    import re

    from ..providers import tmdb, trakt
    from ..services import notify

    if "trakt.tv" in body.list:
        cfg = notify.get_config(db, "trakt", {"client_id": ""})
        try:
            items = trakt.list_items(body.list, cfg["client_id"])
        except trakt.TraktError as e:
            raise HTTPException(400, str(e))
        entries = [{"type": "movie" if i["type"] == "movie" else "tv", "label": f"{i['title']} ({i['year'] or '?'})",
                    "tmdb_id": i["tmdb"], "imdb": i["imdb"]} for i in items]
        return _add_entries(db, entries, body.search_now)
    m = re.search(r"(\d{3,})", body.list)
    if not m:
        raise HTTPException(400, "Enter a TMDB list id or URL, or a trakt.tv link")
    try:
        items = tmdb.list_items(m.group(1))
    except tmdb.TmdbError as e:
        raise HTTPException(502, str(e))
    entries = [{"type": "movie" if i["media_type"] == "movie" else "tv", "label": f"{i['title']} ({i['year'] or '?'})",
                "tmdb_id": i["id"], "tmdb_tv_id": i["id"]} for i in items if i["media_type"] in ("movie", "tv")]
    return _add_entries(db, entries, body.search_now)


def _guess_rows(db: Session) -> list[dict]:
    rows = []
    for path, g in scan_service.get_guessed(db).items():
        item = (db.query(Movie).filter_by(tmdb_id=g["id"]).first() if g["kind"] == "movie"
                else db.query(Series).filter_by(tvmaze_id=g["id"]).first())
        if not item or item.path != path:
            continue  # already changed or removed
        rows.append({"path": path, "name": Path(path).name, "kind": g["kind"], "score": g["score"],
                     "title": item.title, "year": item.year, "poster_url": item.poster_url})
    return sorted(rows, key=lambda r: r["score"])


@router.get("/guessed")
def guessed(db: Session = Depends(get_db)):
    """Folders linked by best guess rather than an exact match, lowest confidence first."""
    return _guess_rows(db)


@router.post("/guessed/confirm")
def confirm_guess(body: PathIn, db: Session = Depends(get_db)):
    g = scan_service.get_guessed(db)
    g.pop(body.path, None)
    scan_service.set_guessed(db, g)
    return {"left": len(g)}


@router.post("/guessed/confirm-all")
def confirm_all(db: Session = Depends(get_db)):
    scan_service.set_guessed(db, {})
    return {"left": 0}


@router.post("/guessed/undo")
def undo_guess(body: PathIn, db: Session = Depends(get_db)):
    """Wrong guess: unlink the folder again (it goes back to the unmatched list; no files are touched)."""
    g = scan_service.get_guessed(db)
    info = g.pop(body.path, None)
    if info:
        item = (db.query(Movie).filter_by(tmdb_id=info["id"]).first() if info["kind"] == "movie"
                else db.query(Series).filter_by(tvmaze_id=info["id"]).first())
        if item and item.path == body.path:
            db.delete(item)
        db.commit()
    scan_service.set_guessed(db, g)
    return {"left": len(g)}
