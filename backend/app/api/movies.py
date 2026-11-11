from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Movie, QualityProfile, RootFolder
from ..providers import tmdb
from ..services import library_files, grab, naming, rules
from ..services.errors import GrabBlocked

from datetime import date as _date_cls


def _date(v):
    try:
        return _date_cls.fromisoformat(v) if v else None
    except ValueError:
        return None


router = APIRouter(prefix="/api/v1/movies", tags=["movies"])


class MovieAdd(BaseModel):
    tmdb_id: int
    root_kind: str | None = None  # movies_kids | movies_adults; omit for rule-based
    monitored: bool = True
    search_now: bool = False
    quality_profile_id: int | None = None
    root_folder_id: int | None = None  # choose the destination folder; omit for the kids/adults rule


def movie_out(m: Movie) -> dict:
    return {
        "id": m.id, "tmdb_id": m.tmdb_id, "title": m.title, "year": m.year,
        "overview": m.overview, "poster_url": m.poster_url, "certification": m.certification,
        "monitored": m.monitored, "has_file": m.has_file, "path": m.path,
        "root_kind": m.root_folder.kind if m.root_folder else None, "quality_profile_id": m.quality_profile_id, "root_folder_id": m.root_folder_id,
        "imdb_id": m.imdb_id, "release_date": m.release_date.isoformat() if m.release_date else None,
    }


@router.get("/lookup")
def lookup(q: str, year: int | None = None, lang: str = "en-US", db: Session = Depends(get_db)):
    try:
        imdb = naming.imdb_id_in(q)
        results = tmdb.find_movie_by_imdb(imdb) if imdb else tmdb.search_movies(q, year, lang)
    except tmdb.TmdbError as e:
        raise HTTPException(502, str(e))
    have = {i for (i,) in db.query(Movie.tmdb_id).filter(Movie.tmdb_id.in_([r["tmdb_id"] for r in results]))}
    return [{**r, "in_library": r["tmdb_id"] in have} for r in results]


@router.get("")
def list_movies(db: Session = Depends(get_db)):
    return [movie_out(m) for m in db.query(Movie).order_by(Movie.title).all()]


@router.post("", status_code=201)
def add_movie(body: MovieAdd, db: Session = Depends(get_db)):
    if db.query(Movie).filter_by(tmdb_id=body.tmdb_id).first():
        raise HTTPException(409, "Movie already in library")
    try:
        d = tmdb.movie_details(body.tmdb_id)
    except tmdb.TmdbError as e:
        raise HTTPException(502, str(e))
    if body.root_folder_id:
        root = db.get(RootFolder, body.root_folder_id)
        if not root or not root.kind.startswith("movies"):
            raise HTTPException(400, "Choose one of the movie folders as destination")
    else:
        kind = body.root_kind or rules.pick_movie_kind(rules.get_rules(db), d["certification"], d["genres"])
        root = (db.query(RootFolder).filter_by(kind=kind).first()
                or db.query(RootFolder).filter(RootFolder.kind.in_(["movies", "movies_kids", "movies_adults"])).first())
        if not root:
            raise HTTPException(400, "No movie folder is set up. Add one under Settings → Library → Media folders.")
    profile = (db.get(QualityProfile, body.quality_profile_id) if body.quality_profile_id else None) \
        or db.query(QualityProfile).filter_by(is_default=True).first() or db.query(QualityProfile).first()
    movie = Movie(
        tmdb_id=d["tmdb_id"], title=d["title"], year=d["year"], overview=d["overview"],
        poster_url=d["poster_url"], certification=d["certification"], imdb_id=d.get("imdb_id"), release_date=_date(d.get("release_date")), monitored=body.monitored,
        root_folder_id=root.id, quality_profile_id=profile.id if profile else None,
        path=f"{root.path}/{naming.folder_name(d['title'], d['year'])}",
    )
    db.add(movie)
    db.commit()
    out = movie_out(movie)
    if body.search_now:
        try:
            item = grab.search_movie(db, movie)
            out["grabbed"] = item.title if item else None
        except GrabBlocked as e:
            out["search_error"] = str(e)
    return out


class MoviePatch(BaseModel):
    monitored: bool | None = None
    quality_profile_id: int | None = None
    root_folder_id: int | None = None


@router.patch("/{movie_id}")
def patch_movie(movie_id: int, body: MoviePatch, db: Session = Depends(get_db)):
    m = db.get(Movie, movie_id)
    if not m:
        raise HTTPException(404)
    if body.monitored is not None:
        m.monitored = body.monitored
    if body.quality_profile_id is not None:
        if not db.get(QualityProfile, body.quality_profile_id):
            raise HTTPException(400, "Unknown profile")
        m.quality_profile_id = body.quality_profile_id
    if body.root_folder_id is not None and body.root_folder_id != m.root_folder_id:
        root = db.get(RootFolder, body.root_folder_id)
        if not root or not root.kind.startswith("movies"):
            raise HTTPException(400, "Choose one of the movie folders")
        if m.has_file:
            raise HTTPException(400, "This movie is already on disk. Moving files is not done automatically: "
                                     "move the folder yourself, or remove the movie from the library and add it again.")
        m.root_folder_id = root.id
        m.path = f"{root.path}/{naming.folder_name(m.title, m.year)}"
    db.commit()
    return movie_out(m)


@router.delete("/{movie_id}", status_code=204)
def delete_movie(movie_id: int, delete_files: bool = False, db: Session = Depends(get_db)):
    item = db.get(Movie, movie_id)
    if not item:
        raise HTTPException(404)
    if delete_files:
        try:
            library_files.delete_library_path(db, item.path)
        except library_files.UnsafePath as e:
            raise HTTPException(400, str(e))
    db.delete(item)
    db.commit()
