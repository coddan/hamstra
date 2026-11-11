from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..indexers import manager, registry
from ..models import Indexer
from ..services.parser import parse

router = APIRouter(prefix="/api/v1/indexers", tags=["indexers"])


class IndexerIn(BaseModel):
    name: str
    kind: str = "torznab"
    url: str = ""
    api_key: str = ""
    username: str = ""
    cookie: str = ""
    user_agent: str = ""
    categories: str = ""
    enabled: bool = True
    priority: int = 25
    seed_ratio: float | None = None
    seed_hours: float | None = None


def validate(body: IndexerIn, existing: Indexer | None = None) -> None:
    try:
        spec = registry.get(body.kind)
    except ValueError as e:
        raise HTTPException(400, str(e))
    for f in spec["fields"]:
        have = getattr(body, f["name"]) or (getattr(existing, f["name"], "") if existing else "")
        if f["required"] and not have:
            raise HTTPException(400, f"{f['label']} is required for {spec['label']}")
    if not body.url:
        body.url = spec["default_url"]


def out(i: Indexer) -> dict:
    return {"id": i.id, "name": i.name, "kind": i.kind, "url": i.url, "username": i.username,
            "categories": i.categories, "user_agent": i.user_agent, "enabled": i.enabled,
            "priority": i.priority, "failures": i.failures, "last_error": i.last_error,
            "seed_ratio": i.seed_ratio, "seed_hours": i.seed_hours,
            "has_key": bool(i.api_key), "has_cookie": bool(i.cookie)}


@router.get("/kinds")
def kinds():
    return registry.public_kinds()


@router.get("")
def list_indexers(db: Session = Depends(get_db)):
    return [out(i) for i in db.query(Indexer).order_by(Indexer.priority).all()]


@router.post("", status_code=201)
def create(body: IndexerIn, db: Session = Depends(get_db)):
    if db.query(Indexer).filter_by(name=body.name).first():
        raise HTTPException(409, "Name already used")
    validate(body)
    ix = Indexer(**body.model_dump())
    try:
        registry.get(ix.kind)["test"](ix)
    except Exception as e:
        raise HTTPException(400, f"Indexer test failed: {e}")
    db.add(ix)
    db.commit()
    return out(ix)


@router.put("/{ix_id}")
def update(ix_id: int, body: IndexerIn, db: Session = Depends(get_db)):
    ix = db.get(Indexer, ix_id)
    if not ix:
        raise HTTPException(404)
    validate(body, ix)
    data = body.model_dump()
    for secret in ("api_key", "cookie"):
        if not data[secret]:
            data[secret] = getattr(ix, secret)
    for k, v in data.items():
        setattr(ix, k, v)
    ix.failures, ix.disabled_until = 0, None
    db.commit()
    return out(ix)


class IndexerPatch(BaseModel):
    enabled: bool | None = None
    priority: int | None = None


@router.patch("/{ix_id}")
def patch(ix_id: int, body: IndexerPatch, db: Session = Depends(get_db)):
    ix = db.get(Indexer, ix_id)
    if not ix:
        raise HTTPException(404)
    if body.priority is not None:
        if not 1 <= body.priority <= 50:
            raise HTTPException(400, "Priority must be between 1 (best) and 50")
        ix.priority = body.priority
    if body.enabled is not None:
        ix.enabled = body.enabled
        if body.enabled:
            ix.failures, ix.disabled_until = 0, None
    db.commit()
    return out(ix)


@router.delete("/{ix_id}", status_code=204)
def delete(ix_id: int, db: Session = Depends(get_db)):
    ix = db.get(Indexer, ix_id)
    if not ix:
        raise HTTPException(404)
    db.delete(ix)
    db.commit()


@router.post("/{ix_id}/test")
def test(ix_id: int, db: Session = Depends(get_db)):
    ix = db.get(Indexer, ix_id)
    if not ix:
        raise HTTPException(404)
    try:
        registry.get(ix.kind)["test"](ix)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/search")
def search(q: str, db: Session = Depends(get_db)):
    results, errors = manager.search_all(db, q)
    return {
        "errors": errors,
        "results": [
            {"title": r.title, "indexer": r.indexer, "size": r.size, "seeders": r.seeders,
             "download_url": r.download_url, "info_hash": r.info_hash,
             "parsed": {k: v for k, v in parse(r.title).__dict__.items() if k != "raw"}}
            for r in sorted(results, key=lambda r: -r.seeders)
        ],
    }
