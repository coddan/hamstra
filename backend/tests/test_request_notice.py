from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Movie, QueueItem, Request, User
from app.services import notify
from app.services.request_notice import mark_available


def test_request_becomes_available(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "send", lambda db, msg: sent.append(msg))
    with TestClient(app), SessionLocal() as db:
        db.query(Request).delete(); db.query(Movie).filter_by(tmdb_id=9901).delete(); db.query(User).filter_by(username="reqer").delete()
        u = User(username="reqer", password_hash="x")
        m = Movie(tmdb_id=9901, title="Asked For", year=2025)
        db.add_all([u, m]); db.commit()
        db.add_all([Request(user_id=u.id, kind="movie", external_id=9901, title="Asked For", status="approved"),
                    Request(user_id=u.id, kind="movie", external_id=1, title="Other", status="approved")])
        db.commit()
        item = QueueItem(title="Asked.For.2025.1080p", kind="movie", movie_id=m.id)
        assert mark_available(db, item) == 1
        assert [r.status for r in db.query(Request).order_by(Request.external_id)] == ["approved", "available"]
        assert sent == ["Now available: Asked For (requested by reqer)"]
        assert mark_available(db, item) == 0                      # only once
        db.query(Request).delete(); db.query(Movie).filter_by(tmdb_id=9901).delete(); db.query(User).filter_by(username="reqer").delete(); db.commit()
