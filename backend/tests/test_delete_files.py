from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Movie, RootFolder, Series


def test_delete_with_files(tmp_path):
    root = tmp_path / "movies"
    folder = root / "Film (2010)"
    folder.mkdir(parents=True)
    (folder / "Film (2010).mkv").write_text("v")
    outside = tmp_path / "other"
    outside.mkdir()
    (outside / "keep.txt").write_text("k")
    with TestClient(app) as c, SessionLocal() as db:
        db.query(Movie).delete()
        db.query(RootFolder).delete()
        r = RootFolder(path=str(root), kind="movies_adults")
        db.add(r)
        db.flush()
        a = Movie(tmdb_id=1, title="Film", year=2010, root_folder_id=r.id, path=str(folder))
        b = Movie(tmdb_id=2, title="Evil", year=2010, root_folder_id=r.id, path=str(outside))
        c_ = Movie(tmdb_id=3, title="Root", year=2010, root_folder_id=r.id, path=str(root))
        db.add_all([a, b, c_])
        db.commit()
        ids = (a.id, b.id, c_.id)

        assert c.delete(f"/api/v1/movies/{ids[0]}").status_code == 204            # no files option: disk untouched
        assert folder.exists()
        db.add(Movie(tmdb_id=1, title="Film", year=2010, root_folder_id=r.id, path=str(folder)))
        db.commit()
        again = db.query(Movie).filter_by(tmdb_id=1).first().id
        assert c.delete(f"/api/v1/movies/{again}?delete_files=true").status_code == 204
        assert not folder.exists() and root.exists()

        assert c.delete(f"/api/v1/movies/{ids[1]}?delete_files=true").status_code == 400   # outside any root
        assert (outside / "keep.txt").exists()
        assert c.delete(f"/api/v1/movies/{ids[2]}?delete_files=true").status_code == 400   # the root itself
        assert root.exists()
