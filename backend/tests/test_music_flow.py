import json

from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.engines import factory
from app.engines.base import TorrentStatus
from app.indexers.torznab import Result
from app.main import app
from app.models import Album, Blocklist, QueueItem, RootFolder, Setting
from app.providers import musicbrainz
from tests.test_e2e import FakeEngine

ALBUM = {"mbid": "f5093c06-23e3-404f-aeaa-40f72885ee3a", "title": "The Dark Side of the Moon", "artist": "Pink Floyd",
         "artist_mbid": "a", "year": 1973, "kind": "Album", "cover_url": "http://c"}


def setup(tmp_path, monkeypatch, layout="artist"):
    from app.migrate import run_migrations
    run_migrations()
    root = tmp_path / "musik"
    (root / "¤ROCK¤" / "Pink Floyd").mkdir(parents=True)
    (root / "¤METAL¤").mkdir()
    monkeypatch.setattr(settings, "downloads_dir", tmp_path / "dl")
    (tmp_path / "dl").mkdir()
    monkeypatch.setattr(musicbrainz, "search_albums", lambda q, limit=20: [ALBUM])
    monkeypatch.setattr(musicbrainz, "search_artists", lambda q, limit=10: [{"mbid": "a", "name": "Pink Floyd", "disambiguation": "", "country": "GB", "type": "Group"}])
    monkeypatch.setattr(musicbrainz, "artist_albums", lambda m: [ALBUM, {**ALBUM, "mbid": "x2", "title": "The Wall", "year": 1979}])
    with SessionLocal() as db:
        db.query(QueueItem).delete(); db.query(Blocklist).delete(); db.query(Album).delete(); db.query(RootFolder).filter_by(kind="music").delete()
        db.add(RootFolder(path=str(root), kind="music"))
        db.merge(Setting(key="music", value=json.dumps({"layout": layout})))
        db.commit()
    return root


def test_search_add_and_locations(tmp_path, monkeypatch):
    root = setup(tmp_path, monkeypatch)
    (root / "¤ROCK¤" / "Pink Floyd" / "The Wall (1979)").mkdir()
    (root / "¤ROCK¤" / "Pink Floyd" / "The Wall (1979)" / "01.flac").write_text("x")
    with TestClient(app) as c:
        assert c.get("/api/v1/music/folders").json()["folders"] == ["¤METAL¤", "¤ROCK¤"]
        assert c.get("/api/v1/music/search?q=pink floyd").json()[0]["in_library"] is False
        assert c.get("/api/v1/music/search?q=pink&type=artist").json()[0]["name"] == "Pink Floyd"
        assert [a["title"] for a in c.get("/api/v1/music/artists/a/albums").json()] == ["The Dark Side of the Moon", "The Wall"]
        assert c.get("/api/v1/music/search?q=%20").status_code == 400

        # new album by an artist that already has a folder: it goes next to the artist, no genre needed
        a = c.post("/api/v1/music/albums", json=ALBUM).json()
        assert a["has_files"] is False and a["genre"] == "¤ROCK¤"
        assert a["path"] == str(root / "¤ROCK¤" / "Pink Floyd" / "The Dark Side of the Moon (1973)")
        assert c.post("/api/v1/music/albums", json=ALBUM).status_code == 409
        # an album already on disk is recognised
        w = c.post("/api/v1/music/albums", json={**ALBUM, "mbid": "x2", "title": "The Wall", "year": 1979}).json()
        assert w["has_files"] is True and w["path"].endswith("The Wall (1979)")
        # explicit genre folder for an artist that is new
        n = c.post("/api/v1/music/albums", json={**ALBUM, "mbid": "x3", "artist": "Iron Maiden", "title": "Powerslave", "year": 1984, "genre": "¤METAL¤"}).json()
        assert n["path"] == str(root / "¤METAL¤" / "Iron Maiden" / "Powerslave (1984)")
        # changing the genre is allowed only while it is not on disk
        assert c.patch(f"/api/v1/music/albums/{n['id']}", json={"genre": "¤ROCK¤"}).json()["path"].startswith(str(root / "¤ROCK¤"))
        assert c.patch(f"/api/v1/music/albums/{w['id']}", json={"genre": "¤METAL¤"}).status_code == 400
        assert c.post("/api/v1/music/albums", json={**ALBUM, "mbid": "x4", "genre": "../evil"}).status_code == 400


def test_search_grab_import_flow(tmp_path, monkeypatch):
    root = setup(tmp_path, monkeypatch)
    dl = tmp_path / "dl"
    rel = dl / "Pink_Floyd-The_Dark_Side_Of_The_Moon-CD-FLAC-1993-GRP"
    (rel / "CD1").mkdir(parents=True)
    (rel / "CD1" / "01 - Speak to Me.flac").write_text("a")
    (rel / "CD1" / "02 - Breathe.flac").write_text("b")
    (rel / "cover.jpg").write_text("img")
    (rel / "release.nfo").write_text("nfo")
    (rel / "release.sfv").write_text("sfv")
    (rel / "Proof").mkdir()
    (rel / "Proof" / "proof.jpg").write_text("p")
    feed = [Result("Pink Floyd - The Wall FLAC", "ix", "magnet:x", "1" * 40, 400_000_000, 50),
            Result("Pink Floyd - The Dark Side of the Moon MP3 128", "ix", "magnet:x", "2" * 40, 90_000_000, 80),
            Result(rel.name, "ix", "magnet:?xt=urn:btih:" + "a" * 40, "a" * 40, 500_000_000, 30)]
    monkeypatch.setattr("app.indexers.manager.search_all", lambda db, q, mode="search", **kw: (feed if mode == "music" else [], []))
    eng = FakeEngine(dl)
    eng.done = True
    eng.list = lambda: [TorrentStatus("a" * 40, "x", 1.0, "seeding", str(rel))]
    factory.set_engine(eng)
    with TestClient(app) as c:
        a = c.post("/api/v1/music/albums", json=ALBUM).json()
        rows = c.get(f"/api/v1/music/albums/{a['id']}/releases").json()["releases"]
        assert rows[0]["title"] == rel.name and rows[0]["accepted"]
        assert any("mp3-128 not allowed" in r["reasons"] for r in rows) and any("not this artist/album" in r["reasons"] for r in rows)

        assert c.post(f"/api/v1/music/albums/{a['id']}/search").json()["grabbed"] == rel.name
        assert c.post(f"/api/v1/music/albums/{a['id']}/search").json()["grabbed"] is None        # already queued
        assert c.post("/api/v1/commands/sync-queue").json()["imported"] == 1

        dest = root / "¤ROCK¤" / "Pink Floyd" / "The Dark Side of the Moon (1973)"
        assert sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()) == [
            "CD1/01 - Speak to Me.flac", "CD1/02 - Breathe.flac", "cover.jpg"]                   # no nfo/sfv/proof
        assert (rel / "CD1" / "01 - Speak to Me.flac").exists()                                  # original still seeds
        got = [x for x in c.get("/api/v1/music/albums").json() if x["id"] == a["id"]][0]
        assert got["has_files"] and got["file_format"] == "flac"
        assert "2 tracks" in c.get("/api/v1/history").json()[0]["detail"]
    factory.set_engine(None)


def test_music_profile_api():
    with TestClient(app) as c:
        p = c.get("/api/v1/music/profile").json()
        assert "flac" in p["allowed"] and "all_qualities" in p
        r = c.put("/api/v1/music/profile", json={"allowed": ["flac"], "order": ["mp3-320"], "reject_words": "live"}).json()
        assert r["allowed"] == ["flac"] and r["order"][0] == "mp3-320" and "flac" in r["order"]     # list kept complete
        assert c.put("/api/v1/music/profile", json={"allowed": ["vhs"]}).status_code == 400
        assert c.put("/api/v1/music/profile", json={"allowed": []}).status_code == 400
        c.put("/api/v1/music/profile", json={"allowed": ["flac", "flac-24", "mp3-320", "mp3-v0", "mp3-v2"], "order": [], "reject_words": "live"})


def test_scene_style_library_detection_and_import(tmp_path, monkeypatch):
    """The real library: <genre>/<release folder> with scene names, no artist folders."""
    root = setup(tmp_path, monkeypatch, layout="release")
    (root / "¤METAL¤" / "Amon_Amarth-Deceiver_of_the_Gods-2CD-LIMITED_DELUX_EDITION-2013-JD").mkdir()
    (root / "¤METAL¤" / "Amon_Amarth-Deceiver_of_the_Gods-2CD-LIMITED_DELUX_EDITION-2013-JD" / "01.flac").write_text("x")
    (root / "¤METAL¤" / "Amon_Amarth_-_Fate_of_Norns-Retail-2004-SPIRIT_INT").mkdir()
    (root / "¤METAL¤" / "A------------").mkdir()                                  # placeholder folders are harmless
    dl = tmp_path / "dl"
    rel = dl / "Amon_Amarth-Twilight_of_the_Thunder_God-CD-FLAC-2008-GRP"
    rel.mkdir(parents=True)
    (rel / "01 - Twilight.flac").write_text("t")
    monkeypatch.setattr(musicbrainz, "search_albums", lambda q, limit=20: [])
    feed = [Result(rel.name, "ix", "magnet:?xt=urn:btih:" + "a" * 40, "a" * 40, 300_000_000, 30)]
    monkeypatch.setattr("app.indexers.manager.search_all", lambda db, q, mode="search", **kw: (feed if mode == "music" else [], []))
    eng = FakeEngine(dl)
    eng.done = True
    eng.list = lambda: [TorrentStatus("a" * 40, "x", 1.0, "seeding", str(rel))]
    factory.set_engine(eng)
    base = {"artist": "Amon Amarth", "artist_mbid": "m", "kind": "Album", "cover_url": None}
    with TestClient(app) as c:
        have = c.post("/api/v1/music/albums", json={**base, "mbid": "s1", "title": "Deceiver of the Gods", "year": 2013}).json()
        assert have["has_files"] is True and have["genre"] == "¤METAL¤"
        assert have["path"].endswith("2013-JD")                                  # found the scene-named folder
        # new album by the same artist: the genre is learned from where the artist already lives
        new = c.post("/api/v1/music/albums", json={**base, "mbid": "s2", "title": "Twilight of the Thunder God", "year": 2008}).json()
        assert new["has_files"] is False and new["genre"] == "¤METAL¤" and new["path"] is None
        assert c.post(f"/api/v1/music/albums/{new['id']}/search").json()["grabbed"] == rel.name
        assert c.post("/api/v1/commands/sync-queue").json()["imported"] == 1
        dest = root / "¤METAL¤" / rel.name                                       # keeps the release's own folder name
        assert (dest / "01 - Twilight.flac").read_text() == "t"
        got = [x for x in c.get("/api/v1/music/albums").json() if x["id"] == new["id"]][0]
        assert got["has_files"] and got["path"] == str(dest)
        # an artist that is nowhere yet: no genre is guessed, the explicit choice is used
        other = c.post("/api/v1/music/albums", json={**base, "artist": "Someone New", "mbid": "s3", "title": "Debut", "year": 2020, "genre": "¤ROCK¤"}).json()
        assert other["genre"] == "¤ROCK¤"
    factory.set_engine(None)


def test_layout_setting_validation():
    with TestClient(app) as c:
        assert c.put("/api/v1/music/profile", json={"layout": "nonsense"}).status_code == 400
        assert c.put("/api/v1/music/profile", json={"layout": "artist"}).json()["layout"] == "artist"
        assert c.put("/api/v1/music/profile", json={"layout": "release"}).json()["layout"] == "release"
