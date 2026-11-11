from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..indexers import manager
from ..indexers.torznab import Result
from ..services import grab
from ..services.errors import GrabBlocked

router = APIRouter(prefix="/api/v1/others", tags=["others"])


@router.get("/search")
def search(q: str, db: Session = Depends(get_db)):
    """Free-text search on every enabled indexer. No filtering by quality rules: this is for anything."""
    if not q.strip():
        raise HTTPException(400, "Enter something to search for")
    results, errors = manager.search_all(db, q.strip(), "search")
    return {
        "errors": errors,
        "results": [
            {"title": r.title, "indexer": r.indexer, "category": r.category, "size": r.size, "seeders": r.seeders,
             "peers": r.peers, "download_url": r.download_url, "info_hash": r.info_hash,
             "published": r.published.isoformat() if r.published else None}
            for r in sorted(results, key=lambda r: -r.seeders)
        ],
    }


class OtherGrab(BaseModel):
    title: str
    download_url: str
    info_hash: str | None = None
    indexer: str = "manual"


@router.post("/grab", status_code=201)
def grab_result(body: OtherGrab, db: Session = Depends(get_db)):
    try:
        item = grab.grab(db, Result(title=body.title, download_url=body.download_url, info_hash=body.info_hash,
                                    indexer=body.indexer), "other")
    except GrabBlocked as e:
        raise HTTPException(503, str(e))
    return {"id": item.id, "title": item.title}


@router.post("/upload", status_code=201)
async def upload(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    added, failed = [], []
    for f in files:
        data = await f.read(grab.MAX_UPLOAD_BYTES + 1)
        try:
            item = grab.grab_uploaded(db, data, "other")
            added.append({"id": item.id, "title": item.title})
        except GrabBlocked as e:
            raise HTTPException(503, str(e))
        except ValueError as e:
            failed.append({"file": f.filename, "error": str(e)})
        except Exception as e:  # engine problems: report per file, keep going
            failed.append({"file": f.filename, "error": f"could not add: {e}"})
    return {"added": added, "failed": failed}


class Magnet(BaseModel):
    magnet: str
    title: str | None = None


@router.post("/magnet", status_code=201)
def magnet(body: Magnet, db: Session = Depends(get_db)):
    try:
        item = grab.grab_magnet(db, body.magnet.strip(), "other", body.title)
    except GrabBlocked as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": item.id, "title": item.title}
