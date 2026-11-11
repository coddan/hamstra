import logging
import sqlite3

from fastapi.testclient import TestClient

from app.main import app
from app.services import backup


def test_health_logs_backups():
    with TestClient(app) as c:
        h = c.get("/api/v1/system/health").json()
        names = {x["name"] for x in h["checks"]}
        assert {"Database", "TMDB", "Download folder", "Indexers", "Torrent client", "VPN", "Plex"} <= names
        assert next(x for x in h["checks"] if x["name"] == "Database")["status"] == "ok"

        logging.getLogger("arr.test").warning("hello from the test")
        logging.getLogger("arr.test").info("just info")
        rows = c.get("/api/v1/system/logs?level=WARNING").json()
        assert rows[0]["msg"] == "hello from the test" and all(r["level"] != "INFO" for r in rows)

        r = c.post("/api/v1/system/backups")
        assert r.status_code == 201
        name = r.json()["name"]
        assert name in [b["name"] for b in c.get("/api/v1/system/backups").json()]
        data = c.get(f"/api/v1/system/backups/{name}")
        assert data.status_code == 200 and data.content[:15] == b"SQLite format 3"
        assert c.get("/api/v1/system/backups/..%2F..%2Fetc%2Fpasswd").status_code == 404
        assert c.get("/api/v1/system/backups/notabackup.db").status_code == 404
        con = sqlite3.connect(backup.backup_dir() / name)
        assert con.execute("select count(*) from root_folders").fetchone()[0] >= 0   # a usable database
        con.close()
