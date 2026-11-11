"""RSS-style sync: fetch each indexer's newest releases once and match them against wanted items."""
import logging
from datetime import date

from sqlalchemy.orm import Session

from ..indexers import manager
from ..models import Album, Episode, Movie, QueueItem, Series
from . import decision, grab, music, naming, refresh
from .music_parser import name_matches
from .errors import GrabBlocked
from .parser import parse

log = logging.getLogger("hamstra.rss")


def _key(title: str) -> str:
    return naming.normalize(title)


def sync(db: Session) -> dict:
    stats = {"releases": 0, "matched": 0, "grabbed": 0, "errors": []}
    today = date.today()

    movies: dict[str, list[Movie]] = {}
    for m in db.query(Movie).filter_by(monitored=True).all():
        prof = grab.profile_for(db, m.quality_profile_id)
        if not (m.has_file and (m.file_resolution or 0) >= prof.cutoff):
            movies.setdefault(_key(m.title), []).append(m)

    shows: dict[str, list[tuple[Series, Episode]]] = {}
    for s in db.query(Series).filter_by(monitored=True).all():
        prof = grab.profile_for(db, s.quality_profile_id)
        for e in s.episodes:
            if e.monitored and e.air_date and e.air_date <= today and not (e.has_file and (e.file_resolution or 0) >= prof.cutoff):
                shows.setdefault(_key(s.title), []).append((s, e))

    albums = db.query(Album).filter_by(monitored=True, has_files=False).all()
    if not movies and not shows and not albums:
        return stats
    results, errors = manager.search_all(db, "", mode="search")
    stats["releases"], stats["errors"] = len(results), errors
    blocked = grab.blocked(db)

    # group candidate releases per wanted target
    targets: dict[tuple, tuple[decision.Want, object, list]] = {}
    for r in results:
        for a in albums:
            if name_matches(r.title, a.artist, a.title):
                targets.setdefault(("a", a.id), (None, a, []))[2].append(r)
        rel = parse(r.title)
        key = _key(rel.title)
        if rel.is_tv and rel.air_date is not None:       # daily show: match by air date
            for s, e in shows.get(key, []):
                if e.air_date == rel.air_date:
                    targets.setdefault(("e", e.id), (grab.episode_want(s, e), (s, e), []))[2].append(r)
        elif rel.absolute is not None and not rel.is_tv and key in shows:  # anime style: Show - 137
            for s, e in shows.get(key, []):
                if s.absolute_numbering and refresh.absolute_numbers(s).get((e.season, e.number)) == rel.absolute:
                    targets.setdefault(("e", e.id), (grab.episode_want(s, e), (s, e), []))[2].append(r)
        elif rel.is_tv:
            if rel.season_pack or not rel.episodes:
                continue
            for s, e in shows.get(key, []):
                if e.season == rel.season and e.number in rel.episodes:
                    targets.setdefault(("e", e.id), (grab.episode_want(s, e), (s, e), []))[2].append(r)
        else:
            for m in movies.get(key, []):
                targets.setdefault(("m", m.id), (grab.movie_want(m), m, []))[2].append(r)
    stats["matched"] = len(targets)

    for (kind, _id), (want, obj, rels) in targets.items():
        if kind == "a":
            if grab.in_queue(db, album_id=obj.id) or db.query(QueueItem).filter(QueueItem.status.in_(grab.ACTIVE)).count() >= grab.MAX_ACTIVE:
                continue
            top = music.best(rels, obj, music.get_profile(db), blocked)
            if top:
                try:
                    grab.grab(db, top.result, "album", album=obj)
                    stats["grabbed"] += 1
                except GrabBlocked as ex:
                    stats["blocked"] = str(ex)
                    break
            continue
        if kind == "m":
            if grab.in_queue(db, movie_id=obj.id):
                continue
            prof = grab.profile_for(db, obj.quality_profile_id)
        else:
            s, e = obj
            if grab.in_queue(db, episode_id=e.id):
                continue
            prof = grab.profile_for(db, s.quality_profile_id)
        if db.query(QueueItem).filter(QueueItem.status.in_(grab.ACTIVE)).count() >= grab.MAX_ACTIVE:
            break
        best = decision.best(rels, want, prof, blocked)
        if not best:
            continue
        try:
            if kind == "m":
                grab.grab(db, best.result, "movie", movie=obj)
            else:
                grab.grab(db, best.result, "episode", series=s, episodes=[e])
            stats["grabbed"] += 1
        except GrabBlocked as ex:
            log.warning("rss sync paused: %s", ex)
            stats["blocked"] = str(ex)
            break
    return stats
