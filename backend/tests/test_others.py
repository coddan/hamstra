from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.engines import factory
from app.engines.base import TorrentStatus
from app.indexers.torznab import Result
from app.main import app
from app.models import History, Movie, QueueItem, RootFolder
from app.services.bencode import info_hash
from tests.test_e2e import FakeEngine


def make_torrent(name: str, length: int = 5) -> bytes:
    info = b"d6:lengthi%de4:name%d:%s12:piece lengthi16384e6:pieces20:" % (length, len(name), name.encode()) + b"x" * 20 + b"e"
    return b"d8:announce3:foo4:info" + info + b"e"


def test_upload_and_download_without_import(tmp_path, monkeypatch):
    dl = tmp_path / "dl"
    (dl / "Cool.App.v1.2").mkdir(parents=True)
    (dl / "Cool.App.v1.2" / "setup.exe").write_text("binary")
    monkeypatch.setattr(settings, "downloads_dir", dl)
    t = make_torrent("Cool.App.v1.2")
    h = info_hash(t)
    state = {"done": False, "stat": (0.0, 0)}
    removed = []
    eng = FakeEngine(dl)
    eng.list = lambda: [TorrentStatus(h, "x", 1.0 if state["done"] else 0.3, "downloading", str(dl / "Cool.App.v1.2"),
                                      ratio=state["stat"][0], seeding_seconds=state["stat"][1])]
    eng.remove = lambda hh, delete_files=False: removed.append((hh, delete_files))
    factory.set_engine(eng)
    with TestClient(app) as c, SessionLocal() as db:
        db.query(QueueItem).delete()
        db.commit()
        r = c.post("/api/v1/others/upload", files=[("files", ("a.torrent", t, "application/x-bittorrent")),
                                                   ("files", ("bad.torrent", b"<html>nope</html>", "application/x-bittorrent"))])
        assert r.status_code == 201
        body = r.json()
        assert [a["title"] for a in body["added"]] == ["Cool.App.v1.2"]
        assert body["failed"][0]["file"] == "bad.torrent" and "not a valid" in body["failed"][0]["error"]
        q = c.get("/api/v1/queue").json()
        assert q[0]["kind"] == "other" and q[0]["status"] == "downloading"

        state["done"] = True                                   # finished: no import, not touched, keeps seeding
        c.post("/api/v1/commands/sync-queue")
        q = c.get("/api/v1/queue").json()
        assert q[0]["status"] == "seeding"
        assert (dl / "Cool.App.v1.2" / "setup.exe").exists()
        assert any(h_["event"] == "downloaded" for h_ in c.get("/api/v1/history").json())

        state["stat"] = (1.4, 100)                             # rule met: torrent removed, files KEPT
        c.post("/api/v1/commands/sync-queue")
        assert removed == [(h, False)]
        assert c.get("/api/v1/queue").json() == []
        assert (dl / "Cool.App.v1.2" / "setup.exe").exists()
        assert "files kept" in c.get("/api/v1/history").json()[0]["detail"]
    factory.set_engine(None)


def test_magnet_and_search_and_grab(tmp_path, monkeypatch):
    dl = tmp_path / "dl"
    dl.mkdir()
    monkeypatch.setattr(settings, "downloads_dir", dl)
    factory.set_engine(FakeEngine(dl))
    feed = [Result("Photo.Editor.2025.x64", "IPT", "magnet:?xt=urn:btih:" + "7" * 40, "7" * 40, 700_000_000, 12, category="Appz"),
            Result("Some.Game.Repack", "IPT", "magnet:?xt=urn:btih:" + "8" * 40, "8" * 40, 5_000_000_000, 80, category="Games")]
    monkeypatch.setattr("app.indexers.manager.search_all", lambda db, q, mode="search", **kw: (feed, []))
    with TestClient(app) as c, SessionLocal() as db:
        db.query(QueueItem).delete()
        db.commit()
        res = c.get("/api/v1/others/search?q=photo").json()["results"]
        assert [x["category"] for x in res] == ["Games", "Appz"]            # sorted by seeders
        assert c.get("/api/v1/others/search?q=%20").status_code == 400
        g = c.post("/api/v1/others/grab", json={"title": res[1]["title"], "download_url": res[1]["download_url"],
                                                "info_hash": res[1]["info_hash"], "indexer": "IPT"})
        assert g.status_code == 201
        assert c.post("/api/v1/others/magnet", json={"magnet": "https://evil"}).status_code == 400
        m = c.post("/api/v1/others/magnet", json={"magnet": "magnet:?xt=urn:btih:" + "9" * 40 + "&dn=My+Thing"})
        assert m.json()["title"] == "My+Thing" or m.json()["title"] == "My Thing"
        kinds = {i["kind"] for i in c.get("/api/v1/queue").json()}
        assert kinds == {"other"}
    factory.set_engine(None)


def test_uploaded_torrent_for_a_movie_is_imported(tmp_path, monkeypatch):
    dl = tmp_path / "dl"
    rel = dl / "Mine.Movie.2018.1080p.BluRay.x264-G"
    rel.mkdir(parents=True)
    (rel / "mine.mkv").write_text("film")
    monkeypatch.setattr(settings, "downloads_dir", dl)
    t = make_torrent("Mine.Movie.2018.1080p.BluRay.x264-G")
    eng = FakeEngine(dl)
    eng.list = lambda: [TorrentStatus(info_hash(t), "x", 1.0, "seeding", str(rel))]
    factory.set_engine(eng)
    with TestClient(app) as c, SessionLocal() as db:
        db.query(QueueItem).delete()
        db.commit()
        root = RootFolder(path=str(tmp_path / "m"), kind="movies_adults")
        db.add(root)
        db.flush()
        mv = Movie(tmdb_id=4747, title="Mine Movie", year=2018, root_folder_id=root.id, path=str(tmp_path / "m" / "Mine Movie (2018)"))
        db.add(mv)
        db.commit()
        r = c.post("/api/v1/grab/upload", files={"file": ("x.torrent", t, "application/x-bittorrent")}, data={"movie_id": str(mv.id)})
        assert r.status_code == 201
        assert c.post("/api/v1/commands/sync-queue").json()["imported"] == 1
        assert (tmp_path / "m" / "Mine Movie (2018)" / "Mine Movie (2018).mkv").read_text() == "film"
        assert c.post("/api/v1/grab/upload", files={"file": ("x.torrent", b"junk", "x")}, data={"movie_id": str(mv.id)}).status_code == 400
        assert c.post("/api/v1/grab/upload", files={"file": ("x.torrent", t, "x")}).status_code == 400   # no target
    factory.set_engine(None)
