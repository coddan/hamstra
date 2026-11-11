"""VPN kill switch: with a VPN interface configured, nothing is grabbed or downloaded while it is down."""
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from ..engines.factory import engine_config

log = logging.getLogger("hamstra.vpn")
IFF_UP = 0x1
_paused_by_us: set[str] = set()


from .errors import GrabBlocked


class VpnDown(GrabBlocked):
    pass


def interface_up(name: str) -> bool:
    base = Path("/sys/class/net") / name
    try:
        # tun/wg report operstate "unknown", so test the IFF_UP flag instead
        return bool(int((base / "flags").read_text().strip(), 16) & IFF_UP)
    except (OSError, ValueError):
        return False


def watched_interface(db: Session) -> str:
    return (engine_config(db).get("bind_interface") or "").strip()


def status(db: Session) -> dict:
    name = watched_interface(db)
    return {"configured": bool(name), "interface": name or None, "up": interface_up(name) if name else None}


def ensure_up(db: Session) -> None:
    s = status(db)
    if s["configured"] and not s["up"]:
        raise VpnDown(f"VPN interface {s['interface']} is down; downloads are paused")


def enforce(db: Session, engine) -> None:
    """Pause active torrents while the VPN is down and resume the ones we paused when it returns."""
    s = status(db)
    if not s["configured"]:
        return
    try:
        if not s["up"]:
            for t in engine.list():
                if t.state in ("downloading", "seeding", "queued", "checking"):
                    engine.pause(t.info_hash)
                    _paused_by_us.add(t.info_hash)
            if _paused_by_us:
                log.warning("VPN down: paused %d torrents", len(_paused_by_us))
        elif _paused_by_us:
            for h in list(_paused_by_us):
                engine.resume(h)
                _paused_by_us.discard(h)
            log.info("VPN back: resumed torrents")
    except Exception as e:
        log.warning("vpn enforcement failed: %s", e)
