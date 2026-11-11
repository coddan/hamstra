import logging
import time
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Episode, Series
from ..providers import tvmaze

log = logging.getLogger("hamstra.refresh")


def merge_episodes(s: Series, items: list[dict]) -> tuple[int, int]:
    """Add new episodes and update titles/dates. Specials (season 0) are matched by title and date, so their numbers
    stay put when TVmaze adds one in between; new specials get the next free number and are not monitored."""
    existing = {(e.season, e.number): e for e in s.episodes if e.season > 0}
    specials = {(e.title, e.air_date): e for e in s.episodes if e.season == 0}
    next_special = max([e.number for e in s.episodes if e.season == 0], default=0) + 1
    added = changed = 0
    for e in items:
        air = date.fromisoformat(e["air_date"]) if e["air_date"] else None
        if e["season"] == 0:
            cur = specials.get((e["title"], air))
            if cur is None:
                cur = Episode(season=0, number=next_special, title=e["title"], air_date=air, monitored=False)
                s.episodes.append(cur)
                specials[(e["title"], air)] = cur
                next_special += 1
                added += 1
            continue
        cur = existing.get((e["season"], e["number"]))
        if cur is None:
            s.episodes.append(Episode(season=e["season"], number=e["number"], title=e["title"], air_date=air, monitored=s.monitored))
            added += 1
        elif cur.title != e["title"] or cur.air_date != air:
            cur.title, cur.air_date = e["title"], air
            changed += 1
    return added, changed


def absolute_numbers(s: Series) -> dict[tuple[int, int], int]:
    """Absolute episode numbers: regular episodes counted in order across seasons (specials excluded)."""
    regular = sorted((e.season, e.number) for e in s.episodes if e.season > 0)
    return {k: i for i, k in enumerate(regular, 1)}


def refresh_series(db: Session, s: Series) -> dict:
    """Re-read show details and the episode list from TVmaze; new episodes follow the series' monitored flag."""
    d = tvmaze.show_details(s.tvmaze_id)
    s.status, s.overview = d["status"], d["overview"] or s.overview
    s.poster_url = d["poster_url"] or s.poster_url
    s.imdb_id, s.tvdb_id = d.get("imdb_id") or s.imdb_id, d.get("tvdb_id") or s.tvdb_id
    added, changed = merge_episodes(s, tvmaze.episodes(s.tvmaze_id))
    s.refreshed_at = datetime.utcnow()
    db.commit()
    return {"series": s.title, "added": added, "changed": changed}


def due(s: Series, now: datetime) -> bool:
    if s.refreshed_at is None:
        return True
    age = now - s.refreshed_at
    return age > (timedelta(days=7) if (s.status or "").lower() == "ended" else timedelta(hours=6))


def refresh_due(db: Session, pause: float = 0.6) -> dict:
    out = {"refreshed": 0, "new_episodes": 0, "failed": 0}
    now = datetime.utcnow()
    for s in db.query(Series).all():
        if not due(s, now):
            continue
        try:
            r = refresh_series(db, s)
            out["refreshed"] += 1
            out["new_episodes"] += r["added"]
            if r["added"]:
                log.info("%s: %d new episode(s)", s.title, r["added"])
        except Exception as e:
            db.rollback()
            out["failed"] += 1
            log.warning("refresh of %s failed: %s", s.title, e)
        time.sleep(pause)  # TVmaze allows about 20 calls per 10 seconds
    return out
