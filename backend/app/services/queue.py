import logging
from concurrent.futures import Future, ThreadPoolExecutor

from sqlalchemy.orm import Session

from ..db import SessionLocal
from datetime import datetime

from ..engines.factory import get_engine
from ..models import Blocklist, History, QueueItem
from . import importer, notify, seeding, vpn

log = logging.getLogger("hamstra.queue")
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="importer")


def _run_import(item_id: int, content_path: str | None) -> bool:
    """Runs in a worker thread with its own DB session (copying/unpacking can take minutes)."""
    with SessionLocal() as db:
        item = db.get(QueueItem, item_id)
        try:
            ok = importer.import_item(db, item, content_path)
        except Exception as e:  # never leave an item stuck in "importing"
            log.exception("import failed for %s", item.title)
            db.rollback()
            item.status, item.error = "failed", f"import error: {e}"
            db.add(History(event="failed", title=item.title, detail=item.error))
            db.commit()
            return False
        return ok


def reset_stuck() -> None:
    """After a restart, imports that were running are retried."""
    with SessionLocal() as db:
        db.query(QueueItem).filter_by(status="importing").update({"status": "completed"})
        db.commit()


def accumulate(item: QueueItem, t) -> tuple[int, int]:
    """Totals that survive engine restarts: when a counter goes backwards the old value is added to a base."""
    if t.uploaded < item.uploaded_last:
        item.uploaded_base += item.uploaded_last
    if t.seeding_seconds < item.seed_last:
        item.seed_base += item.seed_last
    item.uploaded_last, item.seed_last = t.uploaded, t.seeding_seconds
    return item.uploaded_base + t.uploaded, item.seed_base + t.seeding_seconds


def sync(db: Session, wait: bool = False) -> dict:
    engine = get_engine(db)
    vpn.enforce(db, engine)
    status = {t.info_hash: t for t in engine.list()}
    stats = {"updated": 0, "imported": 0, "failed": 0}
    futures: list[Future] = []
    for item in db.query(QueueItem).filter(QueueItem.status.in_(["downloading", "completed"])).all():
        t = status.get(item.info_hash or "")
        if item.status == "downloading":
            if not t:
                item.status, item.error = "failed", "torrent disappeared from client"
            elif t.state == "error":
                item.status, item.error = "failed", "client reported an error"
            else:
                now = datetime.utcnow()
                if t.progress > item.progress or item.progress_changed_at is None:
                    item.progress_changed_at = now
                item.progress = t.progress
                item.save_path = t.save_path
                if t.complete:
                    item.status = "completed"
                elif t.state != "paused" and _stalled(db, item, now):
                    item.status = "failed"
                    item.error = f"stalled: no progress for {seeding.download_rules(db)['stall_hours']:g} hours"
                    try:
                        engine.remove(item.info_hash, delete_files=True)
                    except Exception as e:
                        log.warning("could not remove stalled torrent: %s", e)
            if item.status == "failed":
                db.add(Blocklist(title=item.title, info_hash=item.info_hash, reason=item.error))
                db.add(History(event="failed", title=item.title, detail=item.error))
                notify.send(db, f"Failed: {item.title} ({item.error})")
                stats["failed"] += 1
            stats["updated"] += 1
        if item.status == "completed":
            if item.kind == "other":
                item.status, item.imported_at = "seeding", datetime.utcnow()  # nothing to import: stays in the download folder
                db.add(History(event="downloaded", title=item.title, detail="kept in the download folder (no import)"))
                notify.send(db, f"Downloaded: {item.title}")
            else:
                item.status = "importing"
                db.commit()
                futures.append(_pool.submit(_run_import, item.id, t.save_path if t else None))
    db.commit()
    if wait:
        stats["imported"] += sum(1 for f in futures if f.result())
        db.expire_all()
    for item in db.query(QueueItem).filter_by(status="seeding").all():
        t = status.get(item.info_hash or "")
        if not t:
            item.status = "cleaned"  # already removed from the client
            continue
        item.progress = t.progress
        uploaded, seeded = accumulate(item, t)
        ratio = t.ratio if item.uploaded_base == 0 else uploaded / max(t.size, 1)  # engine's own ratio until a restart
        rules = seeding.rules_for(db, item.indexer)
        if seeding.satisfied(rules, ratio, seeded):
            try:
                engine.remove(item.info_hash, delete_files=item.kind != "other")  # others: keep the files
            except Exception as e:
                log.warning("cleanup failed for %s: %s", item.title, e)
                continue
            item.status = "cleaned"
            db.add(History(event="removed", title=item.title,
                           detail=f"seeding done: ratio {ratio:.2f}, {seeded / 3600:.1f} h, uploaded {uploaded / 1e6:.0f} MB"
                                  + (" – files kept" if item.kind == "other" else "")))
            stats["cleaned"] = stats.get("cleaned", 0) + 1
    db.commit()
    return stats


def _stalled(db: Session, item: QueueItem, now: datetime) -> bool:
    hours = seeding.download_rules(db)["stall_hours"]
    return bool(hours) and item.progress_changed_at is not None and (now - item.progress_changed_at).total_seconds() > hours * 3600


def remove(db: Session, item: QueueItem, blocklist: bool = False, delete_files: bool = False):
    if item.info_hash:
        try:
            get_engine(db).remove(item.info_hash, delete_files)
        except Exception as e:
            log.warning("engine remove failed: %s", e)
    if blocklist:
        db.add(Blocklist(title=item.title, info_hash=item.info_hash, reason="removed by user"))
    db.add(History(event="removed", title=item.title, detail="removed by user" + (" (files deleted)" if delete_files else "")))
    db.delete(item)
    db.commit()
