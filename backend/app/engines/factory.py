import json

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Setting
from .base import Engine

_engine: Engine | None = None
_override: Engine | None = None  # for tests


def set_engine(e: Engine | None):
    global _override
    _override = e


def engine_config(db: Session) -> dict:
    row = db.get(Setting, "engine")
    return {"type": "libtorrent", "url": "", "username": "", "password": "", "bind_interface": "",
            **(json.loads(row.value) if row else {})}


def get_engine(db: Session) -> Engine:
    global _engine
    if _override is not None:
        return _override
    if _engine is None:
        cfg = engine_config(db)
        if cfg["type"] == "qbittorrent":
            from .qbittorrent import QBittorrent
            _engine = QBittorrent(cfg["url"], cfg["username"], cfg["password"])
        else:
            from .libtorrent_engine import LibtorrentEngine
            _engine = LibtorrentEngine(settings.data_dir / "torrents", bind_interface=cfg["bind_interface"] or None)
    return _engine


def reset_engine():
    global _engine
    _engine = None
