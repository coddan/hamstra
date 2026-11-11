from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Movie, Request as Req, Series
from ..services import notify
from . import movies as movies_api
from . import series as series_api
from .auth import current_user, is_admin

router = APIRouter(prefix="/api/v1/requests", tags=["requests"])


class NewRequest(BaseModel):
    kind: str  # movie | series
    external_id: int
    title: str
    year: int | None = None
    poster_url: str | None = None
    overview: str | None = None


def out(r: Req) -> dict:
    return {"id": r.id, "kind": r.kind, "external_id": r.external_id, "title": r.title, "year": r.year,
            "poster_url": r.poster_url, "overview": r.overview, "status": r.status, "note": r.note,
            "user": r.user.username if r.user else None, "created": r.created.isoformat() if r.created else None}


@router.get("")
def list_requests(request: Request, db: Session = Depends(get_db)):
    q = db.query(Req).order_by(Req.id.desc())
    if not is_admin(request, db):
        u = current_user(request, db)
        q = q.filter(Req.user_id == (u.id if u else -1))
    return [out(r) for r in q.all()]


@router.post("", status_code=201)
def create(body: NewRequest, request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        raise HTTPException(400, "Sign in to make requests")
    if body.kind not in ("movie", "series"):
        raise HTTPException(400, "kind must be movie or series")
    exists = (db.query(Movie).filter_by(tmdb_id=body.external_id).first() if body.kind == "movie"
              else db.query(Series).filter_by(tvmaze_id=body.external_id).first())
    if exists:
        raise HTTPException(409, "Already in the library")
    if db.query(Req).filter_by(kind=body.kind, external_id=body.external_id, status="pending").first():
        raise HTTPException(409, "Already requested")
    r = Req(user_id=u.id, **body.model_dump())
    db.add(r)
    db.commit()
    notify.send(db, f"New request from {u.username}: {body.title} ({body.year or '?'})")
    return out(r)


class Approve(BaseModel):
    search_now: bool = True
    quality_profile_id: int | None = None


@router.post("/{rid}/approve")
def approve(rid: int, body: Approve, request: Request, db: Session = Depends(get_db)):
    if not is_admin(request, db):
        raise HTTPException(403, "Admin only")
    r = db.get(Req, rid)
    if not r or r.status != "pending":
        raise HTTPException(404, "No pending request with that id")
    try:
        if r.kind == "movie":
            movies_api.add_movie(movies_api.MovieAdd(tmdb_id=r.external_id, search_now=body.search_now,
                                                     quality_profile_id=body.quality_profile_id), db)
        else:
            series_api.add_series(series_api.SeriesAdd(tvmaze_id=r.external_id, search_now=body.search_now,
                                                       quality_profile_id=body.quality_profile_id), db)
    except HTTPException as e:
        if e.status_code != 409:  # already in the library counts as fulfilled
            raise
    r.status = "approved"
    db.commit()
    notify.send(db, f"Request approved: {r.title}")
    return out(r)


class Deny(BaseModel):
    note: str | None = None


@router.post("/{rid}/deny")
def deny(rid: int, body: Deny, request: Request, db: Session = Depends(get_db)):
    if not is_admin(request, db):
        raise HTTPException(403, "Admin only")
    r = db.get(Req, rid)
    if not r or r.status != "pending":
        raise HTTPException(404, "No pending request with that id")
    r.status, r.note = "denied", body.note
    db.commit()
    return out(r)


@router.delete("/{rid}", status_code=204)
def delete(rid: int, request: Request, db: Session = Depends(get_db)):
    r = db.get(Req, rid)
    if not r:
        raise HTTPException(404)
    u = current_user(request, db)
    if not (is_admin(request, db) or (u and r.user_id == u.id and r.status == "pending")):
        raise HTTPException(403, "You can only withdraw your own pending requests")
    db.delete(r)
    db.commit()
