import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Album, Movie, RootFolder, Series

router = APIRouter(prefix="/api/v1/rootfolders", tags=["rootfolders"])

KINDS = {
    "movies_kids": "Movies (kids)", "movies_adults": "Movies (adults)", "movies": "Movies",
    "tv": "Series", "mixed": "Movies and series (sorted by name)", "music": "Music",
}


def usage(db: Session, r: RootFolder) -> int:
    return (db.query(Movie).filter_by(root_folder_id=r.id).count() + db.query(Series).filter_by(root_folder_id=r.id).count()
            + db.query(Album).filter_by(root_folder_id=r.id).count())


def out(db: Session, r: RootFolder) -> dict:
    return {"id": r.id, "path": r.path, "kind": r.kind, "label": KINDS.get(r.kind, r.kind), "exists": os.path.isdir(r.path),
            "writable": os.path.isdir(r.path) and os.access(r.path, os.W_OK), "items": usage(db, r)}


class RootIn(BaseModel):
    path: str
    kind: str


def _check(body: RootIn) -> str:
    path = body.path.strip().rstrip("/") or "/"
    if not path.startswith("/"):
        raise HTTPException(400, "Use the full path, starting with /")
    if body.kind not in KINDS:
        raise HTTPException(400, f"Type must be one of: {', '.join(KINDS)}")
    return path


@router.get("")
def list_roots(db: Session = Depends(get_db)):
    return {"kinds": KINDS, "folders": [out(db, r) for r in db.query(RootFolder).order_by(RootFolder.id)]}


@router.post("", status_code=201)
def add_root(body: RootIn, db: Session = Depends(get_db)):
    path = _check(body)
    if db.query(RootFolder).filter_by(path=path).first():
        raise HTTPException(409, "That folder is already added")
    for other in db.query(RootFolder).all():   # nested roots would make the same folder show up twice
        if path.startswith(other.path.rstrip("/") + "/") or other.path.startswith(path.rstrip("/") + "/"):
            raise HTTPException(400, f"Overlaps with {other.path}")
    r = RootFolder(path=path, kind=body.kind)
    db.add(r)
    db.commit()
    return out(db, r)


@router.patch("/{rid}")
def change_root(rid: int, body: RootIn, db: Session = Depends(get_db)):
    r = db.get(RootFolder, rid)
    if not r:
        raise HTTPException(404)
    path = _check(body)
    if path != r.path and usage(db, r):
        raise HTTPException(400, "Items already live in this folder, so its path can't change. Add the new path as another folder instead.")
    if db.query(RootFolder).filter(RootFolder.path == path, RootFolder.id != rid).first():
        raise HTTPException(409, "That folder is already added")
    r.path, r.kind = path, body.kind
    db.commit()
    return out(db, r)


@router.delete("/{rid}", status_code=204)
def delete_root(rid: int, detach: bool = False, db: Session = Depends(get_db)):
    r = db.get(RootFolder, rid)
    if not r:
        raise HTTPException(404)
    if usage(db, r):
        if not detach:
            raise HTTPException(409, f"{usage(db, r)} items use this folder. They stay in the library, but are no longer tied to it.")
        for model in (Movie, Series, Album):
            db.query(model).filter_by(root_folder_id=r.id).update({"root_folder_id": None})
    db.delete(r)
    db.commit()
