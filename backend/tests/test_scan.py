from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Episode, Movie, RootFolder, Series


def test_scan_matches(tmp_path):
    tv, movies = tmp_path / "tv", tmp_path / "kids"
    (tv / "Show (2020)").mkdir(parents=True)
    (tv / "Show (2020)" / "Show.S01E01.mkv").write_text("x")
    (tv / "Unknown").mkdir()
    (movies / "Shrek (2001)").mkdir(parents=True)
    (movies / "Shrek (2001)" / "Shrek.mkv").write_text("x")

    with TestClient(app) as c:
        with SessionLocal() as db:
            db.query(Episode).delete(); db.query(Series).delete(); db.query(Movie).delete(); db.query(RootFolder).delete()
            db.add_all([RootFolder(path=str(tv), kind="tv"), RootFolder(path=str(movies), kind="movies_kids")])
            s = Series(tvmaze_id=1, title="Show", year=2020)
            s.episodes.append(Episode(season=1, number=1))
            db.add_all([s, Movie(tmdb_id=1, title="Shrek", year=2001)])
            db.commit()
        r = c.post("/api/v1/library/scan").json()
        assert r["movies_matched"] == 1 and r["episodes_matched"] == 1
        assert [u["path"] for u in r["unmatched"]] == [str(tv / "Unknown")]
