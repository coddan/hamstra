import json

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Album, RootFolder, Setting
from app.providers import musicbrainz
from app.services import music_import


def test_split_name():
    s = music_import.split_name
    assert s("Amon_Amarth-Deceiver_of_the_Gods-2CD-LIMITED_DELUX_EDITION-2013-JD") == ("Amon Amarth", "Deceiver of the Gods", 2013)
    assert s("Amon_Amarth_-_Fate_of_Norns-Retail-2004-SPIRIT_INT") == ("Amon Amarth", "Fate of Norns", 2004)
    assert s("Pink Floyd - The Wall (1979)") == ("Pink Floyd", "The Wall", 1979)
    assert s("JustOneWord") is None


def test_link_existing_albums(tmp_path, monkeypatch):
    root = tmp_path / "musik"
    metal = root / "¤METAL¤"
    for name in ("Amon_Amarth-Deceiver_of_the_Gods-2013-JD", "Unknown_Band-Nothing_Known-2001-GRP", "A----------------------------",
                 "Empty_Folder-No_Audio-2000-GRP"):
        (metal / name).mkdir(parents=True)
    (metal / "Amon_Amarth-Deceiver_of_the_Gods-2013-JD" / "01.flac").write_text("x")
    (metal / "Unknown_Band-Nothing_Known-2001-GRP" / "01.mp3").write_text("x")
    (metal / "Empty_Folder-No_Audio-2000-GRP" / "readme.txt").write_text("x")
    (root / "¤ROCK¤" / "Pink Floyd" / "The Wall (1979)").mkdir(parents=True)                    # Artist/Album layout
    (root / "¤ROCK¤" / "Pink Floyd" / "The Wall (1979)" / "CD1").mkdir()
    (root / "¤ROCK¤" / "Pink Floyd" / "The Wall (1979)" / "CD1" / "01.flac").write_text("x")
    calls = []

    def fake_search(q, limit=20):
        calls.append(q)
        db = {"amon amarth deceiver of the gods": [{"mbid": "m1", "title": "Deceiver of the Gods", "artist": "Amon Amarth", "artist_mbid": "a", "year": 2013, "kind": "Album", "cover_url": None}],
              "pink floyd the wall": [{"mbid": "m2", "title": "The Wall", "artist": "Pink Floyd", "artist_mbid": "b", "year": 1979, "kind": "Album", "cover_url": None},
                                      {"mbid": "m3", "title": "The Wall", "artist": "Someone Else", "artist_mbid": "c", "year": 1979, "kind": "Album", "cover_url": None}]}
        return db.get(q.lower(), [])
    monkeypatch.setattr(musicbrainz, "search_albums", fake_search)
    with TestClient(app) as c, SessionLocal() as db:
        from app.migrate import run_migrations
        db.query(Album).delete(); db.query(RootFolder).filter_by(kind="music").delete()
        db.merge(Setting(key="music_import_tried", value="[]"))
        db.add(RootFolder(path=str(root), kind="music"))
        db.commit()
        out = music_import.run(db, {})
        assert out == {"linked": 2, "not_found": 1, "errors": 0}                                  # placeholder + no-audio skipped
        albums = {a.title: a for a in db.query(Album).all()}
        assert albums["Deceiver of the Gods"].genre == "¤METAL¤" and albums["Deceiver of the Gods"].has_files is True
        assert albums["Deceiver of the Gods"].monitored is False and albums["Deceiver of the Gods"].path.endswith("2013-JD")
        assert albums["The Wall"].artist == "Pink Floyd" and albums["The Wall"].genre == "¤ROCK¤"   # not the other artist's "The Wall"
        n = len(calls)
        assert music_import.run(db, {}) == {"linked": 0, "not_found": 0, "errors": 0} and len(calls) == n   # nothing is looked up twice
        assert music_import.run(db, {}, retry=True)["not_found"] == 1                                 # a retry tries the failures again
        db.query(Album).delete(); db.commit()
        assert [x["title"] for x in c.get("/api/v1/music/albums").json()] == []
