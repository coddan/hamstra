import json
import logging

import httpx
from sqlalchemy.orm import Session

from ..models import Setting

log = logging.getLogger("hamstra.notify")


def get_config(db: Session, name: str, defaults: dict) -> dict:
    row = db.get(Setting, name)
    return {**defaults, **(json.loads(row.value) if row else {})}


def send(db: Session, message: str) -> None:
    url = get_config(db, "notifications", {"webhook_url": ""})["webhook_url"]
    if not url:
        return
    try:
        httpx.post(url, json={"content": message, "text": message}, timeout=10)
    except Exception as e:
        log.warning("notification failed: %s", e)


def plex_refresh(db: Session, path: str | None = None) -> str:
    """Ask Plex to scan. With a path, only that folder is scanned (mapped to Plex's own path) in the matching library."""
    from pathlib import PurePosixPath

    from ..models import RootFolder

    cfg = get_config(db, "plex", {"url": "", "token": "", "section_ids": []})
    if not cfg["url"] or not cfg["token"]:
        return "plex not configured"
    base, headers = cfg["url"].rstrip("/"), {"X-Plex-Token": cfg["token"], "Accept": "application/json"}
    try:
        sections = plex_sections(db)
        targets: list[tuple[str, str | None]] = []
        if path:
            for root in db.query(RootFolder).all():
                if path == root.path or path.startswith(root.path.rstrip("/") + "/"):
                    rel = path[len(root.path):].strip("/")
                    for sec in sections:
                        for folder in sec["folders"]:
                            if PurePosixPath(folder).name == PurePosixPath(root.path).name:
                                targets.append((sec["id"], f"{folder.rstrip('/')}/{rel}" if rel else folder))
        if not targets:  # unknown path: refresh the configured sections, or everything
            wanted = [str(i) for i in cfg["section_ids"]]
            targets = [(sec["id"], None) for sec in sections if not wanted or sec["id"] in wanted]
        for sid, plex_path in targets:
            httpx.get(f"{base}/library/sections/{sid}/refresh", headers=headers,
                      params={"path": plex_path} if plex_path else None, timeout=15).raise_for_status()
        return f"scanned {len(targets)} location(s)"
    except Exception as e:
        log.warning("plex refresh failed: %s", e)
        return f"plex refresh failed: {e}"


def plex_sections(db: Session) -> list[dict]:
    """List Plex libraries with their folders (raises on connection/auth problems)."""
    cfg = get_config(db, "plex", {"url": "", "token": "", "section_ids": []})
    if not cfg["url"] or not cfg["token"]:
        raise ValueError("Plex URL and token are not set")
    r = httpx.get(f"{cfg['url'].rstrip('/')}/library/sections", headers={"X-Plex-Token": cfg["token"], "Accept": "application/json"}, timeout=10)
    if r.status_code == 401:
        raise ValueError("Plex rejected the token")
    r.raise_for_status()
    return [
        {"id": d["key"], "title": d["title"], "type": d["type"], "folders": [l["path"] for l in d.get("Location", [])]}
        for d in r.json()["MediaContainer"].get("Directory", [])
    ]
