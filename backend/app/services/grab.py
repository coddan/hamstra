import logging
from datetime import date

from sqlalchemy.orm import Session

from ..config import settings
from ..engines.factory import get_engine
from ..indexers import manager, registry
from ..indexers.torznab import Result
from ..models import Album, Indexer, Blocklist, Episode, History, Movie, QualityProfile, QueueItem, Series
import shutil

from . import decision, notify, seeding, vpn
from .errors import GrabBlocked, LowDiskSpace

import contextvars

log = logging.getLogger("hamstra.grab")
DRY: contextvars.ContextVar[bool] = contextvars.ContextVar("hamstra_dry_run", default=False)
ACTIVE = ["downloading", "completed", "importing"]


def _csv(text: str | None) -> list[str]:
    return [x.strip().lower() for x in (text or "").split(",") if x.strip()]


def default_profile(db: Session) -> QualityProfile | None:
    return db.query(QualityProfile).filter_by(is_default=True).first() or db.query(QualityProfile).first()


def profile_for(db: Session, profile_id: int | None) -> decision.Profile:
    q = (db.get(QualityProfile, profile_id) if profile_id else None) or default_profile(db)
    if not q:
        return decision.Profile()
    return decision.Profile(
        allowed=[int(x) for x in q.allowed.replace("p", "").split(",") if x], cutoff=q.cutoff,
        min_seeders=q.min_seeders, max_size_gb_movie=q.max_size_gb_movie,
        max_size_mb_episode=q.max_size_mb_episode, prefer_codec=q.prefer_codec,
        sources=_csv(q.sources), source_order=_csv(q.source_order), prefer_words=_csv(q.prefer_words),
        reject_words=_csv(q.reject_words), prefer_hdr=q.prefer_hdr, upgrade_allowed=q.upgrade_allowed,
    )


def blocked(db: Session) -> set[str]:
    out = set()
    for b in db.query(Blocklist).all():
        out.add(b.title)
        if b.info_hash:
            out.add(b.info_hash)
    return out


def movie_want(m: Movie) -> decision.Want:
    return decision.Want("movie", m.title, m.year, current_resolution=m.file_resolution, has_file=m.has_file)


def episode_want(s: Series, e: Episode) -> decision.Want:
    from .refresh import absolute_numbers

    absolute = absolute_numbers(s).get((e.season, e.number)) if s.absolute_numbering else None
    return decision.Want("episode", s.title, s.year, e.season, e.number, e.file_resolution, e.has_file, air_date=e.air_date,
                         absolute=absolute)


def in_queue(db: Session, movie_id: int | None = None, episode_id: int | None = None, album_id: int | None = None) -> bool:
    q = db.query(QueueItem).filter(QueueItem.status.in_(ACTIVE))
    if album_id:
        return q.filter_by(album_id=album_id).first() is not None
    if movie_id:
        return q.filter_by(movie_id=movie_id).first() is not None
    return any(str(episode_id) in i.episode_ids.split(",") for i in q.filter(QueueItem.kind == "episode"))


def _ensure_ids(db: Session, item) -> None:
    """Fill IMDb/TVDB IDs lazily for library items imported before IDs were stored."""
    from ..providers import tmdb, tvmaze

    try:
        if isinstance(item, Movie) and not item.imdb_id:
            item.imdb_id = tmdb.movie_details(item.tmdb_id).get("imdb_id") or ""
        elif isinstance(item, Series) and item.tvdb_id is None and item.imdb_id is None:
            d = tvmaze.show_details(item.tvmaze_id)
            item.imdb_id, item.tvdb_id = d.get("imdb_id") or "", d.get("tvdb_id")
        db.commit()
    except Exception as e:
        db.rollback()
        log.info("could not fetch external ids for %s: %s", item.title, e)


def candidates_movie(db: Session, m: Movie):
    _ensure_ids(db, m)
    return manager.search_all(db, f"{m.title} {m.year or ''}".strip(), "movie", year=m.year, imdb_id=m.imdb_id or None)


def candidates_episode(db: Session, s: Series, e: Episode):
    """Search by season/episode. Daily shows are also searched by air date, absolute-numbered shows by number:
    both are plain text searches, because trackers rarely index those names as season/episode."""
    from .refresh import absolute_numbers

    _ensure_ids(db, s)
    results, errors = manager.search_all(db, s.title, "tvsearch", season=e.season, episode=e.number,
                                         imdb_id=s.imdb_id or None, tvdb_id=s.tvdb_id)
    extra: list[str] = []
    if e.air_date and e.season > 0:
        extra.append(f"{s.title} {e.air_date:%Y %m %d}")
    if s.absolute_numbering and e.season > 0:
        n = absolute_numbers(s).get((e.season, e.number))
        if n:
            extra.append(f"{s.title} {n:02d}")
    seen = {r.download_url for r in results}
    for q in extra:
        more, errs = manager.search_all(db, q, "search")
        errors = [*errors, *errs]
        results += [r for r in more if r.download_url not in seen and not seen.add(r.download_url)]
    return results, errors


def season_want(s: Series, season: int, count: int) -> decision.Want:
    return decision.Want("season", s.title, s.year, season, episode_count=count)


def search_season(db: Session, s: Series, season: int, episodes: list[Episode]) -> QueueItem | None:
    """Look for a complete season pack covering the given (missing) episodes."""
    if any(in_queue(db, episode_id=e.id) for e in episodes):
        return None
    _ensure_ids(db, s)
    results, _ = manager.search_all(db, s.title, "tvsearch", season=season,
                                    imdb_id=s.imdb_id or None, tvdb_id=s.tvdb_id)
    best = decision.best(results, season_want(s, season, len(episodes)), profile_for(db, s.quality_profile_id), blocked(db))
    return grab(db, best.result, "episode", series=s, episodes=episodes) if best else None


def check_disk(db: Session) -> None:
    need = seeding.download_rules(db)["min_free_gb"]
    if not need:
        return
    try:
        free = shutil.disk_usage(settings.downloads_dir).free
    except OSError:
        return  # cannot measure (e.g. folder missing): do not block
    if free < need * 1e9:
        raise LowDiskSpace(f"Only {free / 1e9:.1f} GB free in the download folder (minimum {need:g} GB)")


def grab(db: Session, r: Result, kind: str, movie: Movie | None = None, series: Series | None = None,
         episodes: list[Episode] | None = None, album: Album | None = None) -> QueueItem:
    if DRY.get():  # automatic run in dry-run mode: only record what would have happened
        from . import automation

        what = (movie.title if movie else f"{series.title} S{episodes[0].season:02d}" if series and episodes
                else f"{album.artist} - {album.title}" if album else kind)
        automation.record_would_grab(db, r.title, f"for {what} from {r.indexer}")
        return QueueItem(title=r.title, kind=kind)  # transient, never added to the session
    vpn.ensure_up(db)
    check_disk(db)
    engine = get_engine(db)
    save = str(settings.downloads_dir)
    ix = db.query(Indexer).filter_by(name=r.indexer).first()
    if r.download_url.startswith("magnet:"):
        h = engine.add(r.download_url, save, "hamstra") or r.info_hash
    elif ix is not None:
        data = registry.get(ix.kind)["download"](ix, r.download_url)
        from .bencode import info_hash

        h = engine.add_file(data, save, "hamstra") or info_hash(data)
    else:
        h = engine.add(r.download_url, save, "hamstra") or r.info_hash
    item = QueueItem(
        title=r.title, info_hash=h, kind=kind, movie_id=movie.id if movie else None,
        indexer=r.indexer, album_id=album.id if album else None, series_id=series.id if series else None, episode_ids=",".join(str(e.id) for e in episodes or []),
        save_path=str(settings.downloads_dir),
    )
    db.add(item)
    db.add(History(event="grabbed", title=r.title, detail=f"from {r.indexer}"))
    db.commit()
    notify.send(db, f"Grabbed: {r.title}")
    return item


MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def grab_uploaded(db: Session, data: bytes, kind: str, movie: Movie | None = None, series: Series | None = None,
                  episodes: list[Episode] | None = None, title: str | None = None, album: Album | None = None) -> QueueItem:
    """Add a .torrent file supplied by the user (kind: movie | episode | other)."""
    from .bencode import info_hash, torrent_name

    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Torrent file is too large")
    name = torrent_name(data)  # raises ValueError for anything that is not a torrent
    vpn.ensure_up(db)
    check_disk(db)
    engine = get_engine(db)
    h = engine.add_file(data, str(settings.downloads_dir), "hamstra") or info_hash(data)
    item = QueueItem(
        title=title or name, info_hash=h, kind=kind, indexer="upload", album_id=album.id if album else None,
        movie_id=movie.id if movie else None,
        series_id=series.id if series else None, episode_ids=",".join(str(e.id) for e in episodes or []),
        save_path=str(settings.downloads_dir),
    )
    db.add(item)
    db.add(History(event="grabbed", title=item.title, detail="uploaded torrent file"))
    db.commit()
    notify.send(db, f"Added: {item.title}")
    return item


def grab_magnet(db: Session, magnet: str, kind: str, title: str | None = None, movie: Movie | None = None,
                series: Series | None = None, episodes: list[Episode] | None = None) -> QueueItem:
    import re
    from urllib.parse import parse_qs, urlparse

    if not magnet.startswith("magnet:?") or "xt=urn:btih:" not in magnet:
        raise ValueError("Not a magnet link")
    vpn.ensure_up(db)
    check_disk(db)
    h = get_engine(db).add(magnet, str(settings.downloads_dir), "hamstra")
    m = re.search(r"btih:([0-9a-fA-F]{40}|[A-Z2-7]{32})", magnet)
    name = title or (parse_qs(urlparse(magnet).query).get("dn") or [None])[0] or "Magnet download"
    item = QueueItem(
        title=name, info_hash=(h or (m.group(1).lower() if m and len(m.group(1)) == 40 else None)), kind=kind,
        indexer="magnet", movie_id=movie.id if movie else None, series_id=series.id if series else None,
        episode_ids=",".join(str(e.id) for e in episodes or []), save_path=str(settings.downloads_dir),
    )
    db.add(item)
    db.add(History(event="grabbed", title=item.title, detail="magnet link"))
    db.commit()
    notify.send(db, f"Added: {item.title}")
    return item


def search_album(db: Session, a: Album) -> QueueItem | None:
    from . import music

    if in_queue(db, album_id=a.id):
        return None
    results, _ = manager.search_all(db, f"{a.artist} {a.title}", "music")
    music.enrich(results, a)
    best = music.best(results, a, music.get_profile(db), blocked(db))
    return grab(db, best.result, "album", album=a) if best else None


def search_movie(db: Session, m: Movie) -> QueueItem | None:
    if in_queue(db, movie_id=m.id):
        return None
    results, _ = candidates_movie(db, m)
    best = decision.best(results, movie_want(m), profile_for(db, m.quality_profile_id), blocked(db))
    return grab(db, best.result, "movie", movie=m) if best else None


def search_episode(db: Session, s: Series, e: Episode) -> QueueItem | None:
    if in_queue(db, episode_id=e.id):
        return None
    results, _ = candidates_episode(db, s, e)
    best = decision.best(results, episode_want(s, e), profile_for(db, s.quality_profile_id), blocked(db))
    return grab(db, best.result, "episode", series=s, episodes=[e]) if best else None


MAX_ACTIVE = 5


def search_wanted(db: Session, limit: int = 25) -> dict:
    done = {"searched": 0, "grabbed": 0}
    if vpn.status(db)["up"] is False:
        return done
    if db.query(QueueItem).filter(QueueItem.status.in_(ACTIVE)).count() >= MAX_ACTIVE:
        return done
    today = date.today()
    for m in db.query(Movie).filter_by(monitored=True).all():
        prof = profile_for(db, m.quality_profile_id)
        if m.has_file and (m.file_resolution or 0) >= prof.cutoff:
            continue
        if done["searched"] >= limit:
            return done
        done["searched"] += 1
        done["grabbed"] += bool(search_movie(db, m))
    for s in db.query(Series).filter_by(monitored=True).all():
        if not search_series(db, s, done, limit):
            return done
    for a in db.query(Album).filter_by(monitored=True, has_files=False).all():
        if done["searched"] >= limit or _active(db) >= MAX_ACTIVE:
            return done
        done["searched"] += 1
        done["grabbed"] += bool(search_album(db, a))
    return done


def search_wanted_safe(db: Session, limit: int = 25) -> dict:
    try:
        return search_wanted(db, limit)
    except GrabBlocked as e:
        log.warning("search paused: %s", e)
        return {"searched": 0, "grabbed": 0, "blocked": str(e)}


def _active(db: Session) -> int:
    return db.query(QueueItem).filter(QueueItem.status.in_(ACTIVE)).count()


def search_series(db: Session, s: Series, done: dict, limit: int = 25) -> bool:
    """Search missing episodes of one series (season packs first). Returns False when a limit was hit."""
    today = date.today()
    prof = profile_for(db, s.quality_profile_id)
    missing = [e for e in s.episodes if e.monitored and e.air_date and e.air_date <= today
               and not (e.has_file and (e.file_resolution or 0) >= prof.cutoff) and not in_queue(db, episode_id=e.id)]
    by_season: dict[int, list[Episode]] = {}
    for e in missing:
        by_season.setdefault(e.season, []).append(e)
    for season, eps in by_season.items():
        total = [e for e in s.episodes if e.season == season]
        finished = all(e.air_date and e.air_date <= today for e in total)
        if finished and len(eps) >= 3 and len(eps) * 2 >= len(total):
            if done["searched"] >= limit or _active(db) >= MAX_ACTIVE:
                return False
            done["searched"] += 1
            if search_season(db, s, season, eps):
                done["grabbed"] += 1
                continue
        for e in eps:
            if done["searched"] >= limit or _active(db) >= MAX_ACTIVE:
                return False
            if in_queue(db, episode_id=e.id):
                continue
            done["searched"] += 1
            done["grabbed"] += bool(search_episode(db, s, e))
    return True
