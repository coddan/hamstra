import threading
import time
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Indexer
from . import registry, torznab


MIN_INTERVAL = {"iptorrents": 3.0, "hdbits": 2.0, "torznab": 1.0, "rss": 1.0}  # seconds between requests per indexer
_locks: dict[int, threading.Lock] = {}
_last: dict[int, float] = {}


def pace(ix) -> None:
    """Never hit one tracker faster than MIN_INTERVAL; private trackers ban aggressive clients."""
    lock = _locks.setdefault(ix.id, threading.Lock())
    with lock:
        wait = _last.get(ix.id, 0) + MIN_INTERVAL.get(ix.kind, 1.0) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[ix.id] = time.monotonic()


def search_all(db: Session, query: str, mode: str = "search", season: int | None = None,
               episode: int | None = None, year: int | None = None, categories: str = "",
               imdb_id: str | None = None, tvdb_id: int | None = None) -> tuple[list[torznab.Result], list[dict]]:
    """Search every enabled indexer; a failing indexer is backed off, not fatal."""
    now = datetime.utcnow()
    results, errors = [], []
    for ix in db.query(Indexer).filter_by(enabled=True).order_by(Indexer.priority).all():
        if ix.disabled_until and ix.disabled_until > now:
            continue
        try:
            pace(ix)
            found = registry.get(ix.kind)["search"](ix, query, categories, season, episode, year, mode, imdb_id, tvdb_id)
            ix.failures, ix.last_error, ix.disabled_until = 0, None, None
            for f in found:
                f.priority = ix.priority
            results.extend(found)
        except Exception as e:
            ix.failures += 1
            ix.last_error = str(e)[:200]
            ix.disabled_until = now + timedelta(minutes=min(2 ** ix.failures, 720))
            errors.append({"indexer": ix.name, "error": ix.last_error})
        db.commit()
    return results, errors
