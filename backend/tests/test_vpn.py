import json

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.engines import factory
from app.engines.base import TorrentStatus
from app.main import app
from app.models import Setting
from app.services import vpn


class Eng:
    def __init__(self):
        self.paused, self.resumed = [], []

    def list(self):
        return [TorrentStatus("h1", "x", 0.5, "downloading", "/x")]

    def pause(self, h): self.paused.append(h)
    def resume(self, h): self.resumed.append(h)


def set_iface(name):
    with SessionLocal() as db:
        row = db.get(Setting, "engine")
        data = {"type": "libtorrent", "bind_interface": name}
        if row:
            row.value = json.dumps(data)
        else:
            db.add(Setting(key="engine", value=json.dumps(data)))
        db.commit()


def test_kill_switch(monkeypatch):
    with TestClient(app):
        set_iface("")
        with SessionLocal() as db:
            assert vpn.status(db)["configured"] is False
            vpn.ensure_up(db)  # no-op when no VPN configured
        set_iface("tun-missing0")
        with SessionLocal() as db:
            assert vpn.status(db) == {"configured": True, "interface": "tun-missing0", "up": False}
            with pytest.raises(vpn.VpnDown):
                vpn.ensure_up(db)
            e = Eng()
            vpn.enforce(db, e)
            assert e.paused == ["h1"]
            monkeypatch.setattr(vpn, "interface_up", lambda n: True)
            vpn.enforce(db, e)
            assert e.resumed == ["h1"]
        set_iface("")
