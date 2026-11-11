from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Movie, RootFolder, Series, Setting
from app.providers import tmdb, tvmaze
from app.services import scan as scan_service


def test_looks_like(tmp_path):
    (tmp_path / "Show.Name.S01.1080p").mkdir()
    (tmp_path / "Star Trek Voyager The Complete series").mkdir()
    (tmp_path / "Plain Film (2001)").mkdir()
    col = tmp_path / "Astrid Collection"
    col.mkdir()
    for n in ("Pippi.1969.mkv", "Emil.1971.mkv", "Ronja.1984.mkv"):
        (col / n).write_text("v")
    eps = tmp_path / "Odd Name"
    eps.mkdir()
    for n in (1, 2, 3):
        (eps / f"x.S01E0{n}.mkv").write_text("v")
    assert scan_service.looks_like(tmp_path / "Show.Name.S01.1080p") == "series"
    assert scan_service.looks_like(tmp_path / "Star Trek Voyager The Complete series") == "series"
    assert scan_service.looks_like(tmp_path / "Plain Film (2001)") == "movie"
    assert scan_service.looks_like(col) == "collection"
    assert scan_service.looks_like(eps) == "series"          # no hint in the name, but the files are episodes


def test_auto_match_collections_and_movie_folders_stay_movies(tmp_path, monkeypatch):
    kids = tmp_path / "Barn"
    (kids / "Simpsons.S29.1080p").mkdir(parents=True)
    (kids / "Simpsons.S29.1080p" / "Simpsons.S29E01.mkv").write_text("v")
    col = kids / "Astrid Collection"
    col.mkdir()
    for n in ("Pippi.1969.mkv", "Emil.1971.mkv", "Ronja.1984.mkv"):
        (col / n).write_text("v")
    (kids / "Nonsense Folder").mkdir()
    (kids / "Nonsense Folder" / "a.mkv").write_text("v")

    titles = {"Pippi": (1, 1969), "Emil": (2, 1971), "Ronja": (3, 1984)}

    def fake_movie(q, year=None, language="en-US"):
        for t, (i, y) in titles.items():
            if q.startswith(t):
                return [{"tmdb_id": 9100 + i, "title": t, "original_title": t, "year": y}]
        return []
    monkeypatch.setattr(tmdb, "search_movies_ext", fake_movie)
    monkeypatch.setattr(tmdb, "movie_details", lambda i: {"tmdb_id": i, "title": {9101: "Pippi", 9102: "Emil", 9103: "Ronja"}[i],
                        "year": 2000, "overview": "", "poster_url": None, "certification": "G", "genres": [], "imdb_id": None})
    monkeypatch.setattr(tvmaze, "search_shows", lambda q: [{"tvmaze_id": 6300, "title": "The Simpsons", "year": 1989}] if "simpsons" in q.lower() else [])
    monkeypatch.setattr(tvmaze, "show_details", lambda i: {"tvmaze_id": i, "title": "The Simpsons", "year": 1989, "overview": "", "poster_url": None,
                        "status": "Running", "imdb_id": None, "tvdb_id": None})
    monkeypatch.setattr(tvmaze, "episodes", lambda i: [{"season": 29, "number": 1, "title": "Ep", "air_date": "2017-10-01"}])
    with TestClient(app) as c, SessionLocal() as db:
        db.query(Movie).delete()
        for s in db.query(Series).all():
            db.delete(s)
        db.query(RootFolder).delete()
        db.merge(Setting(key="collection_folders", value="[]"))
        db.merge(Setting(key="ignored_paths", value="[]"))
        db.add_all([RootFolder(path=str(kids), kind="movies_kids"), RootFolder(path=str(tmp_path / "Serier"), kind="tv")])
        db.commit()

        res = scan_service.import_unmatched(db)
        assert str(col) in res["collections"]
        movies = {m.title: m for m in db.query(Movie).all()}
        assert set(movies) == {"Pippi", "Emil", "Ronja"}
        assert movies["Pippi"].path == str(col / "Pippi.1969.mkv") and movies["Pippi"].has_file is True   # per-file matching
        assert db.query(Series).filter_by(tvmaze_id=6300).first() is None     # movie folders hold movies: no series is created there
        left = c.get("/api/v1/library/unmatched").json()
        assert sorted(i["name"] for i in left["items"]) == ["Nonsense Folder", "Simpsons.S29.1080p"]
        assert left["items"][0]["is_dir"] is True
        nonsense = [i for i in left["items"] if i["name"] == "Nonsense Folder"][0]
        info = c.get("/api/v1/library/inspect", params={"path": nonsense["path"]}).json()
        assert info["guess"] == "movie" and info["videos"] == 1
        assert left["collections"] == [str(col)]
        # a human can still resolve the rest, and un-mark a collection
        assert c.post("/api/v1/library/uncollection", json={"path": str(col)}).json()["collections"] == 0


def test_series_without_sxxexx_is_not_a_collection(tmp_path):
    show = tmp_path / "Det var en gang"
    show.mkdir()
    for n in range(1, 7):
        (show / f"Det var en gang - Del {n}.avi").write_text("v")
    films = tmp_path / "Barnfilmer"
    films.mkdir()
    for n in ("Pippi.1969.mkv", "Emil.1971.mkv", "Ronja.1984.mkv"):
        (films / n).write_text("v")
    assert scan_service.looks_like(show) != "collection"
    assert scan_service.looks_like(films) == "collection"


def test_collection_children_skip_subs_and_junk(tmp_path):
    col = tmp_path / "Col"
    (col / "Subs").mkdir(parents=True)
    (col / "Subs" / "x.srt").write_text("s")
    (col / "Extras").mkdir()
    (col / "Extras" / "making.mkv").write_text("v")
    (col / "Film A (2001)").mkdir()
    (col / "Film A (2001)" / "a.mkv").write_text("v")
    (col / "Film B 2002.mkv").write_text("v")
    (col / "empty folder").mkdir()
    names = [p.name for p in scan_service.entries(tmp_path, {str(col)})]
    assert names == ["Film A (2001)", "Film B 2002.mkv"]


def test_lookup_index():
    from types import SimpleNamespace as NS

    items = [NS(title="The Simpsons", year=1989), NS(title="Euphoria (US)", year=2019), NS(title="Alien", year=1979)]
    idx = scan_service.build_index(items)
    assert scan_service.lookup(idx, "Simpsons", None) is items[0]
    assert scan_service.lookup(idx, "Euphoria", 2019) is items[1]            # country suffix ignored
    assert scan_service.lookup(idx, "Alien", 2017) is None                   # wrong year


def test_items_in_the_tv_folder_are_always_series(tmp_path):
    tv = tmp_path / "Serier"
    (tv / "Odd Show Name").mkdir(parents=True)
    (tv / "Odd Show Name" / "a.mkv").write_text("v")
    with TestClient(app) as c, SessionLocal() as db:
        db.query(RootFolder).delete()
        db.merge(Setting(key="collection_folders", value="[]"))
        db.merge(Setting(key="ignored_paths", value="[]"))
        db.add(RootFolder(path=str(tv), kind="tv"))
        db.commit()
        item = c.get("/api/v1/library/unmatched").json()["items"][0]
        assert item["guess"] == "series"
        assert c.get("/api/v1/library/inspect", params={"path": item["path"]}).json()["guess"] == "series"


def test_match_reports_what_it_found(tmp_path, monkeypatch):
    tv = tmp_path / "Serier"
    show = tv / "Some Show"
    show.mkdir(parents=True)
    (show / "Some.Show.S01E01.mkv").write_text("v")
    (show / "Some.Show.S01E02.mkv").write_text("v")
    (tv / "Odd Names").mkdir()
    (tv / "Odd Names" / "Del 1.avi").write_text("v")                         # no S01E01 pattern: cannot be linked
    monkeypatch.setattr(tvmaze, "show_details", lambda i: {"tvmaze_id": i, "title": "Some Show", "year": 2020, "overview": "",
                        "poster_url": None, "status": "Ended", "imdb_id": None, "tvdb_id": None})
    monkeypatch.setattr(tvmaze, "episodes", lambda i: [{"season": 1, "number": n, "title": f"E{n}", "air_date": "2020-01-01"} for n in (1, 2, 3)])
    with TestClient(app) as c, SessionLocal() as db:
        for s in db.query(Series).all():
            db.delete(s)
        db.query(RootFolder).delete()
        db.add(RootFolder(path=str(tv), kind="tv"))
        db.commit()
        r = c.post("/api/v1/library/match", json={"path": str(show), "kind": "tv", "tvmaze_id": 7001}).json()
        assert r["title"] == "Some Show" and r["episodes"] == 3 and r["files_found"] == 2     # 2 of 3 episodes are on disk
        r2 = c.post("/api/v1/library/match", json={"path": str(tv / "Odd Names"), "kind": "tv", "tvmaze_id": 7002}).json()
        assert r2["files_found"] == 0                                                          # linked, but no recognisable file names


def test_guess_pass_follows_folder_type_and_is_undoable(tmp_path, monkeypatch):
    from app.providers import tmdb as tm

    tv, kids = tmp_path / "Serier", tmp_path / "Barn"
    for d in (tv / "Star Trek - Lower Deck", kids / "Crocile Dundee 2 1988", kids / "Nothing Like It 1999"):
        d.mkdir(parents=True)
    (tv / "Star Trek - Lower Deck" / "x.S01E01.mkv").write_text("v")
    (kids / "Crocile Dundee 2 1988" / "a.mkv").write_text("v")
    (kids / "Nothing Like It 1999" / "a.mkv").write_text("v")
    monkeypatch.setattr(tm, "search_movies_ext", lambda q, y=None, language="en-US": [
        {"tmdb_id": 1, "title": "Crocodile Dundee II", "original_title": "Crocodile Dundee II", "year": 1988}] if "dundee" in q.lower() else [])
    monkeypatch.setattr(tm, "movie_details", lambda i: {"tmdb_id": i, "title": "Crocodile Dundee II", "year": 1988, "overview": "",
                        "poster_url": None, "certification": "PG", "genres": [], "imdb_id": None})
    monkeypatch.setattr(tvmaze, "search_shows", lambda q: [{"tvmaze_id": 31, "title": "Star Trek: Lower Decks", "year": 2020}] if "star trek" in q.lower() else [])
    monkeypatch.setattr(tvmaze, "show_details", lambda i: {"tvmaze_id": i, "title": "Star Trek: Lower Decks", "year": 2020, "overview": "",
                        "poster_url": None, "status": "Running", "imdb_id": None, "tvdb_id": None})
    monkeypatch.setattr(tvmaze, "episodes", lambda i: [{"season": 1, "number": 1, "title": "E", "air_date": "2020-08-06"}])
    with TestClient(app) as c, SessionLocal() as db:
        db.query(Movie).delete()
        for s in db.query(Series).all():
            db.delete(s)
        db.query(RootFolder).delete()
        for k in ("collection_folders", "ignored_paths", "guessed_matches", "duplicate_folders"):
            db.merge(Setting(key=k, value="{}" if k in ("guessed_matches", "duplicate_folders") else "[]"))
        db.add_all([RootFolder(path=str(tv), kind="tv"), RootFolder(path=str(kids), kind="movies_kids")])
        db.commit()

        plain = scan_service.import_unmatched(db)                  # exact matching only: nothing is guessed
        assert plain["guessed"] == 0 and db.query(Movie).count() == 0

        res = scan_service.import_unmatched(db, guess=True)
        assert res["guessed"] == 2
        assert db.query(Movie).one().title == "Crocodile Dundee II" and db.query(Series).one().title == "Star Trek: Lower Decks"
        rows = c.get("/api/v1/library/guessed").json()
        assert {r["title"] for r in rows} == {"Crocodile Dundee II", "Star Trek: Lower Decks"} and all(r["score"] > 0.6 for r in rows)
        left = [i["name"] for i in c.get("/api/v1/library/unmatched").json()["items"]]
        assert left == ["Nothing Like It 1999"]                    # no candidate at all: stays for a human

        movie_row = [r for r in rows if r["kind"] == "movie"][0]
        assert c.post("/api/v1/library/guessed/undo", json={"path": movie_row["path"]}).json()["left"] == 1
        assert db.query(Movie).count() == 0                        # the guess is unlinked again, files untouched
        assert (kids / "Crocile Dundee 2 1988" / "a.mkv").exists()
        assert "Crocile Dundee 2 1988" in [i["name"] for i in c.get("/api/v1/library/unmatched").json()["items"]]
        show_row = [r for r in c.get("/api/v1/library/guessed").json()][0]
        assert c.post("/api/v1/library/guessed/confirm", json={"path": show_row["path"]}).json()["left"] == 0
        assert db.query(Series).count() == 1                       # confirmed: stays, no longer listed as a guess
