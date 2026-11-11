from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Album
from ..providers import musicbrainz
from ..services import grab, library_files, music, music_import
from ..services.errors import GrabBlocked

router = APIRouter(prefix="/api/v1/music", tags=["music"])


def out(a: Album) -> dict:
    return {"id": a.id, "mbid": a.mbid, "artist": a.artist, "artist_mbid": a.artist_mbid, "title": a.title, "year": a.year,
            "kind": a.kind, "cover_url": a.cover_url, "monitored": a.monitored, "has_files": a.has_files,
            "file_format": a.file_format, "genre": a.genre, "path": a.path}


def _mb(fn, *args):
    try:
        return fn(*args)
    except musicbrainz.MusicBrainzError as e:
        raise HTTPException(502, str(e))


@router.get("/search")
def search(q: str, type: str = "album", db: Session = Depends(get_db)):
    if not q.strip():
        raise HTTPException(400, "Enter an artist or album")
    if type == "artist":
        return _mb(musicbrainz.search_artists, q)
    results = _mb(musicbrainz.search_albums, q)
    have = {m for (m,) in db.query(Album.mbid).filter(Album.mbid.in_([r["mbid"] for r in results]))}
    return [{**r, "in_library": r["mbid"] in have} for r in results]


@router.get("/artists/{artist_mbid}/albums")
def artist_albums(artist_mbid: str, db: Session = Depends(get_db)):
    results = _mb(musicbrainz.artist_albums, artist_mbid)
    have = {m for (m,) in db.query(Album.mbid).filter(Album.mbid.in_([r["mbid"] for r in results]))}
    return [{**r, "in_library": r["mbid"] in have} for r in results]


@router.get("/folders")
def folders(db: Session = Depends(get_db)):
    root = music.music_root(db)
    if not root:
        return {"root": None, "folders": []}
    return {"root": root.path, "folders": music.genre_folders(Path(root.path))}


@router.get("/albums")
def list_albums(db: Session = Depends(get_db)):
    return [out(a) for a in db.query(Album).order_by(Album.artist, Album.year, Album.title)]


class AlbumAdd(BaseModel):
    mbid: str
    artist: str
    artist_mbid: str | None = None
    title: str
    year: int | None = None
    kind: str | None = None
    cover_url: str | None = None
    genre: str = ""  # folder below the music root; empty = where the artist already is, else the root
    monitored: bool = True
    search_now: bool = False


@router.post("/albums", status_code=201)
def add_album(body: AlbumAdd, db: Session = Depends(get_db)):
    if db.query(Album).filter_by(mbid=body.mbid).first():
        raise HTTPException(409, "Album already in the library")
    root = music.music_root(db)
    if not root:
        raise HTTPException(400, "No music folder is configured")
    if body.genre and body.genre not in music.genre_folders(Path(root.path)):
        if "/" in body.genre or body.genre.startswith("."):
            raise HTTPException(400, "Invalid folder name")  # a new genre folder is created on import
    a = Album(**body.model_dump(exclude={"search_now"}))
    music.locate(db, a)
    db.add(a)
    db.commit()
    res = out(a)
    if body.search_now and not a.has_files:
        try:
            item = grab.search_album(db, a)
            res["grabbed"] = item.title if item else None
        except GrabBlocked as e:
            res["search_error"] = str(e)
    return res


class AlbumPatch(BaseModel):
    monitored: bool | None = None
    genre: str | None = None


@router.patch("/albums/{aid}")
def patch_album(aid: int, body: AlbumPatch, db: Session = Depends(get_db)):
    a = db.get(Album, aid)
    if not a:
        raise HTTPException(404)
    if body.monitored is not None:
        a.monitored = body.monitored
    if body.genre is not None and body.genre != a.genre:
        if a.has_files:
            raise HTTPException(400, "This album is already on disk; move the folder yourself or remove and re-add it")
        if "/" in body.genre or body.genre.startswith("."):
            raise HTTPException(400, "Invalid folder name")
        a.genre = body.genre
        a.path, _ = (str(p) if i == 0 else p for i, p in enumerate(music.target_folder(db, a)))
    db.commit()
    return out(a)


@router.post("/albums/{aid}/rescan")
def rescan(aid: int, db: Session = Depends(get_db)):
    a = db.get(Album, aid)
    if not a:
        raise HTTPException(404)
    music.locate(db, a)
    db.commit()
    return out(a)


@router.delete("/albums/{aid}", status_code=204)
def delete_album(aid: int, delete_files: bool = False, db: Session = Depends(get_db)):
    a = db.get(Album, aid)
    if not a:
        raise HTTPException(404)
    if delete_files and a.has_files:
        try:
            library_files.delete_library_path(db, a.path)
        except library_files.UnsafePath as e:
            raise HTTPException(400, str(e))
    db.delete(a)
    db.commit()


@router.post("/albums/{aid}/search")
def auto_search(aid: int, db: Session = Depends(get_db)):
    a = db.get(Album, aid)
    if not a:
        raise HTTPException(404)
    try:
        item = grab.search_album(db, a)
    except GrabBlocked as e:
        raise HTTPException(503, str(e))
    return {"grabbed": item.title if item else None}


@router.get("/albums/{aid}/releases")
def releases(aid: int, db: Session = Depends(get_db)):
    from ..indexers import manager

    a = db.get(Album, aid)
    if not a:
        raise HTTPException(404)
    results, errors = manager.search_all(db, f"{a.artist} {a.title}", "music")
    music.enrich(results, a)
    prof, blocked = music.get_profile(db), grab.blocked(db)
    rows = []
    for r in results:
        d = music.evaluate(r, a, prof, blocked)
        rows.append({"title": r.title, "indexer": r.indexer, "size": r.size, "seeders": r.seeders, "download_url": r.download_url,
                     "info_hash": r.info_hash, "accepted": d.accepted, "reasons": d.reasons, "score": round(d.score, 1),
                     "resolution": None, "source": d.quality, "codec": None, "hdr": False, "category": r.category,
                     "published": r.published.isoformat() if r.published else None, "priority": r.priority})
    rows.sort(key=lambda x: (not x["accepted"], -x["score"]))
    return {"errors": errors, "releases": rows}


@router.get("/profile")
def get_profile(db: Session = Depends(get_db)):
    return {**music.get_profile(db), "all_qualities": music.ALL_QUALITIES}


@router.put("/profile")
def put_profile(body: dict, db: Session = Depends(get_db)):
    bad = [q for q in body.get("allowed", []) + body.get("order", []) if q not in music.ALL_QUALITIES]
    if bad:
        raise HTTPException(400, f"Unknown quality: {', '.join(bad)}")
    if "layout" in body and body["layout"] not in ("release", "artist"):
        raise HTTPException(400, "layout must be 'release' or 'artist'")
    if "allowed" in body and not body["allowed"]:
        raise HTTPException(400, "Allow at least one format")
    order = body.get("order") or music.DEFAULTS["order"]
    body["order"] = order + [q for q in music.ALL_QUALITIES if q not in order]   # keep the list complete
    return {**music.save_profile(db, body), "all_qualities": music.ALL_QUALITIES}


class ImportIn(BaseModel):
    genre: str | None = None  # limit to one folder below the music root
    retry: bool = False       # also retry folders that did not match last time


@router.post("/import")
def import_existing(body: ImportIn):
    """Link albums already in the music folder to MusicBrainz (slow: about one lookup per second)."""
    return music_import.start(body.genre, body.retry)


@router.get("/import")
def import_status():
    return music_import.JOB
