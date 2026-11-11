from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Episode, QualityProfile, RootFolder, Series
from ..providers import tvmaze
from ..services import library_files, grab, naming
from ..services.errors import GrabBlocked

router = APIRouter(prefix="/api/v1/series", tags=["series"])


class SeriesAdd(BaseModel):
    tvmaze_id: int
    monitored: bool = True
    search_now: bool = False
    quality_profile_id: int | None = None
    root_folder_id: int | None = None


def series_out(s: Series, detail: bool = False) -> dict:
    out = {
        "id": s.id, "tvmaze_id": s.tvmaze_id, "title": s.title, "year": s.year,
        "overview": s.overview, "poster_url": s.poster_url, "status": s.status,
        "monitored": s.monitored, "path": s.path, "quality_profile_id": s.quality_profile_id,
        "episode_count": len(s.episodes), "file_count": sum(e.has_file for e in s.episodes),
    }
    if detail:
        out["episodes"] = [
            {"id": e.id, "season": e.season, "number": e.number, "title": e.title,
             "air_date": e.air_date.isoformat() if e.air_date else None,
             "monitored": e.monitored, "has_file": e.has_file}
            for e in s.episodes
        ]
    return out


def add_series_from_provider(db: Session, tvmaze_id: int, monitored: bool = True, profile_id: int | None = None,
                             root_folder_id: int | None = None) -> Series:
    d = tvmaze.show_details(tvmaze_id)
    root = db.get(RootFolder, root_folder_id) if root_folder_id else db.query(RootFolder).filter_by(kind="tv").first()
    if not root or root.kind != "tv":
        raise HTTPException(400, "No TV folder to put the series in")
    profile = (db.get(QualityProfile, profile_id) if profile_id else None) \
        or db.query(QualityProfile).filter_by(is_default=True).first() or db.query(QualityProfile).first()
    s = Series(
        tvmaze_id=d["tvmaze_id"], title=d["title"], year=d["year"], overview=d["overview"],
        poster_url=d["poster_url"], status=d["status"], imdb_id=d.get("imdb_id"), tvdb_id=d.get("tvdb_id"),
        monitored=monitored,
        root_folder_id=root.id, quality_profile_id=profile.id if profile else None,
        path=f"{root.path}/{naming.folder_name(d['title'], d['year'])}",
    )
    for e in tvmaze.episodes(tvmaze_id):
        s.episodes.append(Episode(
            season=e["season"], number=e["number"], title=e["title"],
            air_date=date.fromisoformat(e["air_date"]) if e["air_date"] else None,
        ))
    db.add(s)
    db.commit()
    return s


@router.get("/lookup")
def lookup(q: str, db: Session = Depends(get_db)):
    imdb = naming.imdb_id_in(q)
    results = tvmaze.lookup_imdb(imdb) if imdb else tvmaze.search_shows(q)
    have = {i for (i,) in db.query(Series.tvmaze_id).filter(Series.tvmaze_id.in_([r["tvmaze_id"] for r in results]))}
    return [{**r, "in_library": r["tvmaze_id"] in have} for r in results]


@router.get("")
def list_series(db: Session = Depends(get_db)):
    return [series_out(s) for s in db.query(Series).order_by(Series.title).all()]


@router.get("/{series_id}")
def get_series(series_id: int, db: Session = Depends(get_db)):
    s = db.get(Series, series_id)
    if not s:
        raise HTTPException(404)
    return series_out(s, detail=True)


@router.post("", status_code=201)
def add_series(body: SeriesAdd, db: Session = Depends(get_db)):
    if db.query(Series).filter_by(tvmaze_id=body.tvmaze_id).first():
        raise HTTPException(409, "Series already in library")
    s = add_series_from_provider(db, body.tvmaze_id, body.monitored, body.quality_profile_id, body.root_folder_id)
    out = series_out(s)
    if body.search_now:
        done = {"searched": 0, "grabbed": 0}
        try:
            grab.search_series(db, s, done)
            out["search"] = done
        except GrabBlocked as e:
            out["search_error"] = str(e)
    return out


class SeriesPatch(BaseModel):
    monitored: bool | None = None
    quality_profile_id: int | None = None


@router.patch("/{series_id}")
def patch_series(series_id: int, body: SeriesPatch, db: Session = Depends(get_db)):
    s = db.get(Series, series_id)
    if not s:
        raise HTTPException(404)
    if body.monitored is not None:
        s.monitored = body.monitored
        for e in s.episodes:
            e.monitored = body.monitored
    if body.quality_profile_id is not None:
        if not db.get(QualityProfile, body.quality_profile_id):
            raise HTTPException(400, "Unknown profile")
        s.quality_profile_id = body.quality_profile_id
    db.commit()
    return series_out(s)


@router.delete("/{series_id}", status_code=204)
def delete_series(series_id: int, delete_files: bool = False, db: Session = Depends(get_db)):
    item = db.get(Series, series_id)
    if not item:
        raise HTTPException(404)
    if delete_files:
        try:
            library_files.delete_library_path(db, item.path)
        except library_files.UnsafePath as e:
            raise HTTPException(400, str(e))
    db.delete(item)
    db.commit()
