from sqlalchemy.orm import Session

from ..models import Movie, QueueItem, Request, Series
from . import notify


def mark_available(db: Session, item: QueueItem) -> int:
    """An approved request becomes 'available' once the title has been imported; the requester is told."""
    if item.kind == "movie":
        m = db.get(Movie, item.movie_id)
        kind, ext, title = "movie", m.tmdb_id if m else None, m.title if m else item.title
    elif item.kind == "episode":
        s = db.get(Series, item.series_id)
        kind, ext, title = "series", s.tvmaze_id if s else None, s.title if s else item.title
    else:
        return 0
    if ext is None:
        return 0
    n = 0
    for r in db.query(Request).filter_by(kind=kind, external_id=ext, status="approved").all():
        r.status = "available"
        n += 1
        notify.send(db, f"Now available: {title} (requested by {r.user.username if r.user else '?'})")
    if n:
        db.commit()
    return n
