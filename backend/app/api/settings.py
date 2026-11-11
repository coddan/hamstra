from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import rules

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class MovieRules(BaseModel):
    kids_certifications: list[str]
    kids_genres: list[str]
    use_genres_when_no_certification: bool
    default_kind: Literal["movies_kids", "movies_adults"]


@router.get("/movie-rules", response_model=MovieRules)
def get_movie_rules(db: Session = Depends(get_db)):
    return rules.get_rules(db)


@router.put("/movie-rules", response_model=MovieRules)
def put_movie_rules(body: MovieRules, db: Session = Depends(get_db)):
    return rules.save_rules(db, body.model_dump())


import json

from fastapi import HTTPException

from ..engines import factory
from ..models import Setting

SECTIONS = {
    "subtitles": {"enabled": False, "api_key": "", "username": "", "password": "", "languages": "sv,en", "limit_per_run": 5},
    "trakt": {"client_id": ""},
    "automation": {"enabled": False, "dry_run": True, "rss": True, "search": True},
    "downloads": {"stall_hours": 6.0, "min_free_gb": 20.0},
    "seeding": {"ratio": 1.0, "hours": 72.0, "mode": "either"},
    "plex": {"url": "", "token": "", "section_ids": []},
    "notifications": {"webhook_url": ""},
    "engine": {"type": "libtorrent", "url": "", "username": "", "password": "", "bind_interface": ""},
}
SECRET = {"token", "password", "webhook_url", "api_key", "client_id"}
MASK = "********"


@router.post("/plex/test")
def plex_test(db: Session = Depends(get_db)):
    from ..services import notify

    try:
        return {"ok": True, "sections": notify.plex_sections(db)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/subtitles/test")
def subtitles_test(db: Session = Depends(get_db)):
    from ..services import subtitles

    cfg = subtitles.config(db)
    try:
        subtitles.OpenSubtitles(cfg["api_key"], cfg["username"], cfg["password"]).login()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/plex/scan")
def plex_scan(path: str | None = None, db: Session = Depends(get_db)):
    from ..services import notify

    return {"result": notify.plex_refresh(db, path)}


@router.get("/{name}")
def get_section(name: str, db: Session = Depends(get_db)):
    if name not in SECTIONS:
        raise HTTPException(404)
    row = db.get(Setting, name)
    data = {**SECTIONS[name], **(json.loads(row.value) if row else {})}
    return {k: (MASK if k in SECRET and v else v) for k, v in data.items()}


@router.put("/{name}")
def put_section(name: str, body: dict, db: Session = Depends(get_db)):
    if name not in SECTIONS:
        raise HTTPException(404)
    row = db.get(Setting, name)
    old = json.loads(row.value) if row else {}
    data = {k: body.get(k, old.get(k, SECTIONS[name][k])) for k in SECTIONS[name]}
    for k in SECRET & data.keys():
        if data[k] == MASK:
            data[k] = old.get(k, "")
    if row:
        row.value = json.dumps(data)
    else:
        db.add(Setting(key=name, value=json.dumps(data)))
    db.commit()
    if name == "engine":
        factory.reset_engine()
    return get_section(name, db)
