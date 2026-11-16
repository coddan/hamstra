import json
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Indexer, Setting

DEFAULTS = {"ratio": 1.0, "hours": 72.0, "mode": "either"}  # either: ratio OR hours; both: ratio AND hours


def get_rules(db: Session) -> dict:
    row = db.get(Setting, "seeding")
    return {**DEFAULTS, **(json.loads(row.value) if row else {})}


def rules_for(db: Session, indexer_name: str | None) -> dict:
    rules = get_rules(db)
    ix = db.query(Indexer).filter_by(name=indexer_name).first() if indexer_name else None
    if ix and ix.seed_ratio is not None:
        rules["ratio"] = ix.seed_ratio
    if ix and ix.seed_hours is not None:
        rules["hours"] = ix.seed_hours
    return rules


def satisfied(rules: dict, ratio: float, seeding_seconds: int) -> bool:
    r_ok = ratio >= rules["ratio"]
    t_ok = seeding_seconds >= rules["hours"] * 3600
    return (r_ok and t_ok) if rules["mode"] == "both" else (r_ok or t_ok)


from ..config import settings

DL_DEFAULTS = {"stall_hours": 6.0, "min_free_gb": settings.min_free_gb,  # 0 disables each check
               "max_download_kbps": 0, "max_upload_kbps": 0,  # KiB/s for all torrents together, 0 = unlimited
               "protect_existing": True}  # never replace or delete a file already in the library


def download_rules(db: Session) -> dict:
    row = db.get(Setting, "downloads")
    return {**DL_DEFAULTS, **(json.loads(row.value) if row else {})}


def apply_limits(db: Session, engine) -> None:
    """Push the speed caps to the torrent client; only talks to it when the values changed."""
    rules = download_rules(db)
    want = (max(0, int(rules["max_download_kbps"] or 0)) * 1024, max(0, int(rules["max_upload_kbps"] or 0)) * 1024)
    if getattr(engine, "_applied_limits", None) == want or not hasattr(engine, "set_limits"):
        return
    engine.set_limits(*want)
    engine._applied_limits = want
