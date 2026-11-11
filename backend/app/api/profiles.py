from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Movie, QualityProfile, Series
from ..services.decision import DEFAULT_SOURCES

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])
RESOLUTIONS = [480, 576, 720, 1080, 2160]


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    resolutions: list[int] = [720, 1080, 2160]
    cutoff: int = 1080
    sources: list[str] = DEFAULT_SOURCES
    source_order: list[str] = DEFAULT_SOURCES
    prefer_codec: str | None = "x265"
    prefer_hdr: bool = False
    prefer_words: str = ""
    reject_words: str = ""
    min_seeders: int = 1
    max_size_gb_movie: float = 30.0
    max_size_mb_episode: float = 4000.0
    upgrade_allowed: bool = True


def out(q: QualityProfile, db: Session | None = None) -> dict:
    return {
        "id": q.id, "name": q.name, "is_default": q.is_default,
        "resolutions": [int(x) for x in q.allowed.replace("p", "").split(",") if x], "cutoff": q.cutoff,
        "sources": [x for x in q.sources.split(",") if x], "source_order": [x for x in q.source_order.split(",") if x],
        "prefer_codec": q.prefer_codec, "prefer_hdr": q.prefer_hdr, "prefer_words": q.prefer_words,
        "reject_words": q.reject_words, "min_seeders": q.min_seeders, "max_size_gb_movie": q.max_size_gb_movie,
        "max_size_mb_episode": q.max_size_mb_episode, "upgrade_allowed": q.upgrade_allowed,
        "in_use": (db.query(Movie).filter_by(quality_profile_id=q.id).count()
                   + db.query(Series).filter_by(quality_profile_id=q.id).count()) if db else None,
    }


def apply(q: QualityProfile, b: ProfileIn) -> None:
    if not b.resolutions:
        raise HTTPException(400, "Pick at least one resolution")
    if any(r not in RESOLUTIONS for r in b.resolutions):
        raise HTTPException(400, f"Resolutions must be among {RESOLUTIONS}")
    if not b.sources or any(s not in DEFAULT_SOURCES for s in b.sources):
        raise HTTPException(400, f"Sources must be among {DEFAULT_SOURCES}")
    order = [s for s in b.source_order if s in DEFAULT_SOURCES]
    order += [s for s in DEFAULT_SOURCES if s not in order]  # keep the list complete
    q.name = b.name.strip()
    q.allowed = ",".join(str(r) for r in sorted(set(b.resolutions)))
    q.cutoff = b.cutoff
    q.sources = ",".join(b.sources)
    q.source_order = ",".join(order)
    q.prefer_codec = (b.prefer_codec or "").lower() or None
    q.prefer_hdr, q.upgrade_allowed = b.prefer_hdr, b.upgrade_allowed
    q.prefer_words = ",".join(w.strip().lower() for w in b.prefer_words.split(",") if w.strip())
    q.reject_words = ",".join(w.strip().lower() for w in b.reject_words.split(",") if w.strip())
    q.min_seeders, q.max_size_gb_movie, q.max_size_mb_episode = b.min_seeders, b.max_size_gb_movie, b.max_size_mb_episode


@router.get("")
def list_profiles(db: Session = Depends(get_db)):
    return [out(q, db) for q in db.query(QualityProfile).order_by(QualityProfile.id)]


@router.post("", status_code=201)
def create(body: ProfileIn, db: Session = Depends(get_db)):
    if db.query(QualityProfile).filter_by(name=body.name.strip()).first():
        raise HTTPException(409, "A profile with that name exists")
    q = QualityProfile()
    apply(q, body)
    db.add(q)
    db.commit()
    return out(q, db)


@router.put("/{pid}")
def update(pid: int, body: ProfileIn, db: Session = Depends(get_db)):
    q = db.get(QualityProfile, pid)
    if not q:
        raise HTTPException(404)
    clash = db.query(QualityProfile).filter(QualityProfile.name == body.name.strip(), QualityProfile.id != pid).first()
    if clash:
        raise HTTPException(409, "A profile with that name exists")
    apply(q, body)
    db.commit()
    return out(q, db)


@router.post("/{pid}/default")
def make_default(pid: int, db: Session = Depends(get_db)):
    q = db.get(QualityProfile, pid)
    if not q:
        raise HTTPException(404)
    db.query(QualityProfile).update({"is_default": False})
    q.is_default = True
    db.commit()
    return out(q, db)


@router.delete("/{pid}", status_code=204)
def delete(pid: int, db: Session = Depends(get_db)):
    q = db.get(QualityProfile, pid)
    if not q:
        raise HTTPException(404)
    if db.query(QualityProfile).count() <= 1:
        raise HTTPException(400, "Cannot delete the last profile")
    default = db.query(QualityProfile).filter(QualityProfile.id != pid, QualityProfile.is_default.is_(True)).first() \
        or db.query(QualityProfile).filter(QualityProfile.id != pid).first()
    for model in (Movie, Series):  # items using it fall back to another profile
        db.query(model).filter_by(quality_profile_id=pid).update({"quality_profile_id": default.id})
    was_default = q.is_default
    db.delete(q)
    if was_default:
        default.is_default = True
    db.commit()
