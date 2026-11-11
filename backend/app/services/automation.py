import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..config import settings
from ..models import History, Setting

KEY = "automation"


def config(db: Session) -> dict:
    row = db.get(Setting, KEY)
    base = {"enabled": settings.auto_search, "dry_run": True, "rss": True, "search": True}
    return {**base, **(json.loads(row.value) if row else {})}


def run(db: Session, kind: str, fn, force: bool = False):
    """Run an automatic job honouring Settings → Automation (kind: rss | search). In dry-run mode nothing is downloaded."""
    from . import grab

    cfg = config(db)
    if not force and not (cfg["enabled"] and cfg[kind]):
        return {"disabled": True}
    token = grab.DRY.set(cfg["dry_run"])
    try:
        res = fn(db)
    finally:
        grab.DRY.reset(token)
    if cfg["dry_run"] and isinstance(res, dict):
        res["dry_run"] = True
    return res


def record_would_grab(db: Session, title: str, detail: str) -> bool:
    """Log a release that would have been grabbed; at most once per day per release."""
    since = datetime.utcnow() - timedelta(days=1)
    if db.query(History).filter(History.event == "would_grab", History.title == title, History.date >= since).first():
        return False
    db.add(History(event="would_grab", title=title, detail=detail))
    db.commit()
    return True
