import os
import shutil

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..engines.factory import get_engine
from ..models import Indexer, RootFolder
from . import notify, seeding, vpn


def _c(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}  # status: ok | warn | error | off


def checks(db: Session) -> list[dict]:
    out = []
    try:
        db.execute(text("select 1"))
        out.append(_c("Database", "ok", "reachable"))
    except Exception as e:
        out.append(_c("Database", "error", str(e)))

    out.append(_c("TMDB", "ok" if settings.tmdb_api_key else "warn",
                  "API key set" if settings.tmdb_api_key else "no HAMSTRA_TMDB_API_KEY: movie lookup will not work"))

    for r in db.query(RootFolder).all():
        if not os.path.isdir(r.path):
            out.append(_c(f"Library folder ({r.kind})", "error", f"{r.path} does not exist"))
        elif not os.access(r.path, os.W_OK):
            out.append(_c(f"Library folder ({r.kind})", "error", f"{r.path} is not writable"))
        else:
            out.append(_c(f"Library folder ({r.kind})", "ok", r.path))

    dl = settings.downloads_dir
    if not os.path.isdir(dl):
        out.append(_c("Download folder", "error", f"{dl} does not exist"))
    else:
        try:
            free = shutil.disk_usage(dl).free / 1e9
            need = seeding.download_rules(db)["min_free_gb"]
            ok = os.access(dl, os.W_OK)
            out.append(_c("Download folder", "error" if not ok else "warn" if need and free < need else "ok",
                          f"{dl} – {free:.0f} GB free" + ("" if ok else " (not writable)")))
        except OSError as e:
            out.append(_c("Download folder", "warn", str(e)))

    ixs = db.query(Indexer).all()
    enabled = [i for i in ixs if i.enabled]
    bad = [i for i in enabled if i.failures]
    if not enabled:
        out.append(_c("Indexers", "warn", "none enabled: nothing can be searched"))
    elif bad:
        out.append(_c("Indexers", "warn", "; ".join(f"{i.name}: {i.last_error}" for i in bad)))
    else:
        out.append(_c("Indexers", "ok", f"{len(enabled)} enabled"))

    try:
        out.append(_c("Torrent client", "ok", f"{len(get_engine(db).list())} torrents"))
    except Exception as e:
        out.append(_c("Torrent client", "error", str(e)[:200]))

    v = vpn.status(db)
    out.append(_c("VPN", "off" if not v["configured"] else "ok" if v["up"] else "error",
                  "not configured" if not v["configured"] else f"{v['interface']} is {'up' if v['up'] else 'DOWN – downloads paused'}"))

    from ..services.notify import get_config
    p = get_config(db, "plex", {"url": "", "token": ""})
    if p["url"] and p["token"]:
        try:
            out.append(_c("Plex", "ok", f"{len(notify.plex_sections(db))} libraries"))
        except Exception as e:
            out.append(_c("Plex", "error", str(e)[:200]))
    else:
        out.append(_c("Plex", "off", "not configured"))
    return out
