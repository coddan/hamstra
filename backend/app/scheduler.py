import logging

from apscheduler.schedulers.background import BackgroundScheduler

from .db import SessionLocal
from .services import automation, backup, grab, queue, refresh, rss, scan, subtitles

log = logging.getLogger("hamstra.scheduler")


LAST: dict[str, dict] = {}


def _run(fn, name: str | None = None):
    job = name or fn.__name__

    def wrapper():
        from datetime import datetime

        with SessionLocal() as db:
            try:
                res = fn(db)
                LAST[job] = {"at": datetime.now().isoformat(timespec="seconds"), "ok": True, "result": str(res)[:200]}
            except Exception as e:
                log.exception("scheduled job %s failed", fn.__name__)
                LAST[job] = {"at": datetime.now().isoformat(timespec="seconds"), "ok": False, "result": str(e)[:200]}
    wrapper.__name__ = job
    return wrapper


def _save_engine():
    from .engines import factory

    e = factory._engine
    if e is not None and hasattr(e, "save_state"):
        e.save_state()


def start() -> BackgroundScheduler:
    sch = BackgroundScheduler()
    sch.add_job(_run(queue.sync), "interval", seconds=30, id="queue", max_instances=1, coalesce=True)
    sch.add_job(_run(lambda db: automation.run(db, "rss", rss.sync), "rss"), "interval", minutes=15, id="rss", max_instances=1, coalesce=True)
    sch.add_job(_run(lambda db: automation.run(db, "search", grab.search_wanted_safe), "search"), "interval", minutes=60, id="search", max_instances=1, coalesce=True)
    sch.add_job(_run(subtitles.run, "subtitles"), "interval", hours=12, id="subtitles", max_instances=1, coalesce=True)
    sch.add_job(_run(refresh.refresh_due, "refresh"), "interval", hours=6, id="refresh", max_instances=1, coalesce=True)
    sch.add_job(_run(scan.scan), "interval", hours=6, id="scan", max_instances=1, coalesce=True)
    sch.add_job(lambda: _run(lambda db: backup.create_backup(), "backup")(), "cron", hour=3, minute=30, id="backup")
    sch.add_job(_save_engine, "interval", seconds=60, id="engine-state", max_instances=1, coalesce=True)
    sch.start()
    return sch
