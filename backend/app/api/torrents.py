"""Add a .torrent file or magnet link from the Movies / Series pages: identify the title, add it to the library, download."""
import re
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Movie, Series
from ..services import grab, matching
from ..services.bencode import torrent_name
from ..services.errors import GrabBlocked
from ..services.parser import parse
from . import movies as movies_api
from . import series as series_api

router = APIRouter(prefix="/api/v1/torrents", tags=["torrents"])


async def _read(file: UploadFile | None, magnet: str | None) -> tuple[bytes | None, str | None, str]:
    """Returns (torrent bytes, magnet, release name)."""
    if file is not None and file.filename:
        data = await file.read(grab.MAX_UPLOAD_BYTES + 1)
        if len(data) > grab.MAX_UPLOAD_BYTES:
            raise HTTPException(400, "Torrent file is too large")
        try:
            return data, None, torrent_name(data)
        except ValueError as e:
            raise HTTPException(400, str(e))
    if magnet and magnet.strip():
        m = magnet.strip()
        if not m.startswith("magnet:?") or "xt=urn:btih:" not in m:
            raise HTTPException(400, "Not a magnet link")
        name = (parse_qs(urlparse(m).query).get("dn") or [""])[0]
        return None, m, name
    raise HTTPException(400, "Choose a .torrent file or paste a magnet link")


@router.post("/inspect")
async def inspect(file: UploadFile | None = File(None), magnet: str | None = Form(None), db: Session = Depends(get_db)):
    data, mag, name = await _read(file, magnet)
    if not name:
        return {"name": "", "kind": None, "title": "", "year": None, "season": None, "episodes": [], "season_pack": False,
                "candidates": [], "note": "This magnet link has no name, so search for the title yourself."}
    rel = parse(name)
    kind = "series" if rel.is_tv else "movie"
    try:
        cands = (matching.candidates_show(rel.title, rel.year) if kind == "series"
                 else matching.candidates_movie(rel.title, rel.year))
    except Exception as e:  # provider down / no TMDB key: the user can still search by hand
        cands, note = [], f"Could not look up suggestions: {e}"
    else:
        note = None
    have = {c["tmdb_id" if kind == "movie" else "tvmaze_id"] for c in cands}
    in_lib = set()
    if have:
        model, col = (Movie, Movie.tmdb_id) if kind == "movie" else (Series, Series.tvmaze_id)
        in_lib = {i for (i,) in db.query(col).filter(col.in_(have))}
    key = "tmdb_id" if kind == "movie" else "tvmaze_id"
    return {"name": name, "kind": kind, "title": rel.title, "year": rel.year, "season": rel.season, "episodes": rel.episodes,
            "season_pack": rel.season_pack, "note": note,
            "candidates": [{**c, "in_library": c[key] in in_lib} for c in cands]}


@router.post("/add", status_code=201)
async def add(file: UploadFile | None = File(None), magnet: str | None = Form(None), kind: str = Form(...),
              tmdb_id: int | None = Form(None), tvmaze_id: int | None = Form(None), season: int | None = Form(None),
              db: Session = Depends(get_db)):
    data, mag, name = await _read(file, magnet)
    try:
        if kind == "movie":
            if not tmdb_id:
                raise HTTPException(400, "Pick the movie this torrent is")
            movie = db.query(Movie).filter_by(tmdb_id=tmdb_id).first()
            if not movie:
                movie = db.get(Movie, movies_api.add_movie(movies_api.MovieAdd(tmdb_id=tmdb_id), db)["id"])
            item = (grab.grab_uploaded(db, data, "movie", movie=movie) if data
                    else grab.grab_magnet(db, mag, "movie", name or None, movie=movie))
            return {"id": item.id, "title": item.title, "library_item": movie.title}

        if kind != "series" or not tvmaze_id:
            raise HTTPException(400, "Pick the series this torrent is")
        series = db.query(Series).filter_by(tvmaze_id=tvmaze_id).first()
        if not series:
            series = series_api.add_series_from_provider(db, tvmaze_id, monitored=False)  # opt in to monitoring yourself
            for e in series.episodes:
                e.monitored = False
            db.commit()
        rel = parse(name) if name else None
        s_no = season if season is not None else (rel.season if rel else None)
        if s_no is None:
            raise HTTPException(400, "Could not tell which season this is: choose the season")
        in_season = [e for e in series.episodes if e.season == s_no]
        if rel and rel.episodes and not rel.season_pack and season is None:
            eps = [e for e in in_season if e.number in rel.episodes]
        else:
            eps = [e for e in in_season if not e.has_file] or in_season
        if not eps:
            raise HTTPException(400, f"No matching episodes found in season {s_no} of {series.title}")
        item = (grab.grab_uploaded(db, data, "episode", series=series, episodes=eps) if data
                else grab.grab_magnet(db, mag, "episode", name or None, series=series, episodes=eps))
        return {"id": item.id, "title": item.title, "library_item": series.title, "season": s_no,
                "episodes": [e.number for e in eps]}
    except GrabBlocked as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
