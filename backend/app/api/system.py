from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import RootFolder
from ..services import backup, health, vpn
from .. import logbuf, scheduler

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/status")
def status():
    return {
        "version": "0.1.0",
        "roots": {
            "tv": str(settings.tv_root),
            "movies_kids": str(settings.movies_kids_root),
            "movies_adults": str(settings.movies_adults_root),
            "downloads": str(settings.downloads_dir),
        },
        "tmdb_configured": bool(settings.tmdb_api_key),
    }


@router.get("/rootfolders")
def root_folders(db: Session = Depends(get_db)):
    return [
        {"id": r.id, "path": r.path, "kind": r.kind, "exists": __import__("os").path.isdir(r.path)}
        for r in db.query(RootFolder).all()
    ]


@router.get("/vpn")
def vpn_status(db: Session = Depends(get_db)):
    return vpn.status(db)


@router.get("/health")
def get_health(db: Session = Depends(get_db)):
    return {"checks": health.checks(db), "jobs": scheduler.LAST}


@router.get("/logs")
def get_logs(level: str = "INFO", limit: int = 200):
    return logbuf.tail(level, min(limit, 1000))


@router.get("/backups")
def list_backups():
    return backup.list_backups()


@router.post("/backups", status_code=201)
def make_backup():
    p = backup.create_backup()
    if not p:
        raise HTTPException(400, "Backups are only supported for the built-in SQLite database")
    return {"name": p.name}


@router.get("/backups/{name}")
def download_backup(name: str):
    p = backup.backup_path(name)
    if not p:
        raise HTTPException(404)
    return FileResponse(p, filename=p.name, media_type="application/octet-stream")


@router.post("/backups/{name}/restore")
def restore_backup(name: str):
    if not backup.stage_restore(name):
        raise HTTPException(404, "Backup not found (or the database is not SQLite)")
    return {"staged": True, "message": "The backup will replace the current database the next time the app starts."}


@router.post("/restart")
def restart_app():
    """Exit the process; a container restart policy (unless-stopped / always) starts it again straight away."""
    import os
    import threading

    threading.Timer(1.0, lambda: os._exit(0)).start()
    return {"restarting": True}
