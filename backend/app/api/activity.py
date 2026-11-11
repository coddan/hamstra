from datetime import date, timedelta

from fastapi import File, Form, UploadFile, APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Album, Blocklist, Episode, History, Movie, QueueItem, Series
from ..indexers import manager
from ..services import decision, grab, queue
from ..services.errors import GrabBlocked
from ..services.parser import parse

router = APIRouter(prefix="/api/v1", tags=["activity"])


def _engine_stats(db: Session) -> dict:
    from ..engines.factory import get_engine

    try:
        return {t.info_hash: t for t in get_engine(db).list()}
    except Exception:
        return {}


@router.get("/queue")
def get_queue(db: Session = Depends(get_db)):
    from ..services import seeding

    live = _engine_stats(db)
    out = []
    for i in db.query(QueueItem).filter(QueueItem.status != "cleaned").order_by(QueueItem.id.desc()).all():
        t = live.get(i.info_hash or "")
        row = {"id": i.id, "title": i.title, "kind": i.kind, "status": i.status, "progress": i.progress,
               "error": i.error, "movie_id": i.movie_id, "series_id": i.series_id, "indexer": i.indexer,
               "added": i.added.isoformat() if i.added else None,
               "imported_at": i.imported_at.isoformat() if i.imported_at else None, "live": None, "rules": None}
        if t:
            row["progress"] = t.progress
            up_total = i.uploaded_base + t.uploaded if t.uploaded >= i.uploaded_last else i.uploaded_base + i.uploaded_last + t.uploaded
            seed_total = i.seed_base + t.seeding_seconds if t.seeding_seconds >= i.seed_last else i.seed_base + i.seed_last + t.seeding_seconds
            row["live"] = {"state": t.state, "size": t.size, "downloaded": t.downloaded, "uploaded": up_total,
                           "ratio": round(up_total / max(t.size, 1), 3) if i.uploaded_base else round(t.ratio, 3),
                           "seeding_seconds": seed_total,
                           "down_rate": t.download_rate, "up_rate": t.upload_rate, "peers": t.peers,
                           "seeds": t.seeders, "eta": t.eta, "paused": t.state == "paused"}
        if i.status == "seeding":
            row["rules"] = seeding.rules_for(db, i.indexer)
        out.append(row)
    return out


def _queue_hash(db: Session, item_id: int) -> str:
    item = db.get(QueueItem, item_id)
    if not item or not item.info_hash:
        raise HTTPException(404, "Queue item has no torrent")
    return item.info_hash


@router.post("/queue/{item_id}/pause")
def pause_item(item_id: int, db: Session = Depends(get_db)):
    from ..engines.factory import get_engine

    get_engine(db).pause(_queue_hash(db, item_id))
    return {"ok": True}


@router.post("/queue/{item_id}/resume")
def resume_item(item_id: int, db: Session = Depends(get_db)):
    from ..engines.factory import get_engine

    get_engine(db).resume(_queue_hash(db, item_id))
    return {"ok": True}


@router.delete("/queue/{item_id}", status_code=204)
def remove_queue(item_id: int, blocklist: bool = False, delete_files: bool = False, db: Session = Depends(get_db)):
    item = db.get(QueueItem, item_id)
    if not item:
        raise HTTPException(404)
    queue.remove(db, item, blocklist, delete_files)


@router.get("/history")
def get_history(limit: int = 100, db: Session = Depends(get_db)):
    return [{"id": h.id, "event": h.event, "title": h.title, "detail": h.detail, "date": h.date.isoformat()}
            for h in db.query(History).order_by(History.id.desc()).limit(limit)]


@router.get("/blocklist")
def get_blocklist(db: Session = Depends(get_db)):
    return [{"id": b.id, "title": b.title, "reason": b.reason} for b in db.query(Blocklist).order_by(Blocklist.id.desc())]


@router.delete("/blocklist/{bid}", status_code=204)
def del_blocklist(bid: int, db: Session = Depends(get_db)):
    b = db.get(Blocklist, bid)
    if b:
        db.delete(b)
        db.commit()


@router.get("/calendar")
def calendar(start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    start = start or date.today() - timedelta(days=7)
    end = end or date.today() + timedelta(days=30)
    rows = (db.query(Episode, Series).join(Series).filter(Episode.air_date >= start, Episode.air_date <= end)
            .order_by(Episode.air_date).all())
    out = [{"type": "episode", "date": e.air_date.isoformat(), "series_id": s.id, "series": s.title, "season": e.season,
            "number": e.number, "title": e.title, "has_file": e.has_file, "monitored": e.monitored and s.monitored} for e, s in rows]
    for m in db.query(Movie).filter(Movie.release_date >= start, Movie.release_date <= end).order_by(Movie.release_date):
        out.append({"type": "movie", "date": m.release_date.isoformat(), "movie_id": m.id, "series": m.title,
                    "season": None, "number": None, "title": m.title, "has_file": m.has_file, "monitored": m.monitored})
    return sorted(out, key=lambda x: x["date"])


@router.post("/commands/search-wanted")
def search_wanted(db: Session = Depends(get_db)):
    from ..services import automation

    return automation.run(db, "search", grab.search_wanted_safe, force=True)  # honours the dry-run setting


@router.post("/series/{sid}/refresh")
def refresh_one(sid: int, db: Session = Depends(get_db)):
    from ..services import refresh

    s = db.get(Series, sid)
    if not s:
        raise HTTPException(404)
    try:
        return refresh.refresh_series(db, s)
    except Exception as e:
        raise HTTPException(502, f"TVmaze: {e}")


@router.post("/commands/refresh-series")
def refresh_all(db: Session = Depends(get_db)):
    from ..services import refresh

    return refresh.refresh_due(db)


@router.post("/commands/subtitles")
def run_subtitles(db: Session = Depends(get_db)):
    from ..services import subtitles

    cfg = subtitles.config(db)
    cfg_has = all(cfg[k] for k in ("api_key", "username", "password"))
    if not cfg_has:
        raise HTTPException(400, "Set the API key, username and password under Settings → Subtitles first")
    return subtitles.run(db, client=subtitles.OpenSubtitles(cfg["api_key"], cfg["username"], cfg["password"]))


@router.post("/commands/rss-sync")
def rss_sync(db: Session = Depends(get_db)):
    from ..services import automation, rss

    return automation.run(db, "rss", rss.sync, force=True)


@router.post("/commands/sync-queue")
def sync_queue(db: Session = Depends(get_db)):
    return queue.sync(db, wait=True)


def _releases(db, results, errors, want, profile):
    blocked = grab.blocked(db)
    out = []
    for r in results:
        d = decision.evaluate(r, want, profile, blocked)
        out.append({"title": r.title, "indexer": r.indexer, "size": r.size, "seeders": r.seeders,
                    "download_url": r.download_url, "info_hash": r.info_hash, "accepted": d.accepted,
                    "reasons": d.reasons, "score": round(d.score, 1), "resolution": d.release.resolution,
                    "source": d.release.source, "codec": d.release.codec, "hdr": d.release.hdr,
                    "group": d.release.group, "published": r.published.isoformat() if r.published else None,
                    "priority": r.priority})
    out.sort(key=lambda x: (not x["accepted"], -x["score"]))
    return {"errors": errors, "releases": out}


@router.post("/movies/{mid}/search")
def auto_search_movie(mid: int, db: Session = Depends(get_db)):
    m = db.get(Movie, mid)
    if not m:
        raise HTTPException(404)
    item = grab.search_movie(db, m)
    return {"grabbed": item.title if item else None}


@router.get("/movies/{mid}/releases")
def movie_releases(mid: int, db: Session = Depends(get_db)):
    m = db.get(Movie, mid)
    if not m:
        raise HTTPException(404)
    results, errors = grab.candidates_movie(db, m)
    return _releases(db, results, errors, grab.movie_want(m), grab.profile_for(db, m.quality_profile_id))


@router.post("/series/{sid}/episodes/{eid}/search")
def auto_search_episode(sid: int, eid: int, db: Session = Depends(get_db)):
    s, e = db.get(Series, sid), db.get(Episode, eid)
    if not s or not e or e.series_id != s.id:
        raise HTTPException(404)
    item = grab.search_episode(db, s, e)
    return {"grabbed": item.title if item else None}


@router.get("/series/{sid}/episodes/{eid}/releases")
def episode_releases(sid: int, eid: int, db: Session = Depends(get_db)):
    s, e = db.get(Series, sid), db.get(Episode, eid)
    if not s or not e or e.series_id != s.id:
        raise HTTPException(404)
    results, errors = grab.candidates_episode(db, s, e)
    return _releases(db, results, errors, grab.episode_want(s, e), grab.profile_for(db, s.quality_profile_id))


@router.get("/series/{sid}/seasons/{season}/releases")
def season_releases(sid: int, season: int, db: Session = Depends(get_db)):
    s = db.get(Series, sid)
    if not s:
        raise HTTPException(404)
    grab._ensure_ids(db, s)
    results, errors = manager.search_all(db, s.title, "tvsearch", season=season,
                                         imdb_id=s.imdb_id or None, tvdb_id=s.tvdb_id)
    count = len([e for e in s.episodes if e.season == season]) or 1
    return _releases(db, results, errors, grab.season_want(s, season, count), grab.profile_for(db, s.quality_profile_id))


@router.post("/series/{sid}/search")
def search_series_missing(sid: int, db: Session = Depends(get_db)):
    """Automatic search for everything missing in a series (season packs first)."""
    s = db.get(Series, sid)
    if not s:
        raise HTTPException(404)
    done = {"searched": 0, "grabbed": 0}
    try:
        grab.search_series(db, s, done, limit=40)
    except GrabBlocked as e:
        raise HTTPException(503, str(e))
    return done


@router.post("/series/{sid}/seasons/{season}/search")
def search_season_pack(sid: int, season: int, db: Session = Depends(get_db)):
    s = db.get(Series, sid)
    if not s:
        raise HTTPException(404)
    prof = grab.profile_for(db, s.quality_profile_id)
    eps = [e for e in s.episodes if e.season == season and not (e.has_file and (e.file_resolution or 0) >= prof.cutoff)]
    if not eps:
        return {"grabbed": None, "detail": "nothing missing in this season"}
    item = grab.search_season(db, s, season, eps)
    return {"grabbed": item.title if item else None}


class GrabIn(BaseModel):
    title: str
    download_url: str
    info_hash: str | None = None
    indexer: str = "manual"
    movie_id: int | None = None
    album_id: int | None = None
    series_id: int | None = None
    episode_id: int | None = None
    season: int | None = None  # grab for every missing episode of this season (season packs)


@router.post("/grab", status_code=201)
def manual_grab(body: GrabIn, db: Session = Depends(get_db)):
    try:
        return _manual_grab(body, db)
    except GrabBlocked as e:
        raise HTTPException(503, str(e))


def _manual_grab(body: GrabIn, db: Session):
    from ..indexers.torznab import Result

    r = Result(title=body.title, download_url=body.download_url, info_hash=body.info_hash, indexer=body.indexer)
    if body.album_id:
        a = db.get(Album, body.album_id)
        if not a:
            raise HTTPException(404)
        item = grab.grab(db, r, "album", album=a)
    elif body.movie_id:
        m = db.get(Movie, body.movie_id)
        if not m:
            raise HTTPException(404)
        item = grab.grab(db, r, "movie", movie=m)
    else:
        s = db.get(Series, body.series_id)
        if not s:
            raise HTTPException(404)
        if body.season is not None:
            eps = [e for e in s.episodes if e.season == body.season and not e.has_file]
            if not eps:
                raise HTTPException(400, "No missing episodes in that season")
        else:
            e = db.get(Episode, body.episode_id)
            if not e:
                raise HTTPException(404)
            eps = [e]
        item = grab.grab(db, r, "episode", series=s, episodes=eps)
    return {"id": item.id}


@router.post("/grab/upload", status_code=201)
async def grab_upload(file: UploadFile = File(...), movie_id: int | None = Form(None), album_id: int | None = Form(None), series_id: int | None = Form(None),
                      episode_id: int | None = Form(None), season: int | None = Form(None),
                      db: Session = Depends(get_db)):
    """Attach a .torrent the user found themselves to a movie, episode or season; it is imported like any grab."""
    data = await file.read(grab.MAX_UPLOAD_BYTES + 1)
    try:
        if album_id:
            a = db.get(Album, album_id)
            if not a:
                raise HTTPException(404, "Album not found")
            item = grab.grab_uploaded(db, data, "album", album=a)
        elif movie_id:
            m = db.get(Movie, movie_id)
            if not m:
                raise HTTPException(404, "Movie not found")
            item = grab.grab_uploaded(db, data, "movie", movie=m)
        elif series_id:
            s = db.get(Series, series_id)
            if not s:
                raise HTTPException(404, "Series not found")
            if season is not None:
                eps = [e for e in s.episodes if e.season == season and not e.has_file]
            else:
                e = db.get(Episode, episode_id) if episode_id else None
                eps = [e] if e else []
            if not eps:
                raise HTTPException(400, "No matching missing episode(s)")
            item = grab.grab_uploaded(db, data, "episode", series=s, episodes=eps)
        else:
            raise HTTPException(400, "Give movie_id or series_id")
    except GrabBlocked as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": item.id, "title": item.title}
