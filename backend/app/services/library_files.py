import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import RootFolder


class UnsafePath(Exception):
    pass


def delete_library_path(db: Session, path: str | None) -> bool:
    """Delete a movie/series folder or file, only when it sits strictly inside a library root."""
    if not path:
        return False
    target = Path(path).resolve()
    roots = [Path(r.path).resolve() for r in db.query(RootFolder).all()]
    if any(target == r for r in roots) or not any(r in target.parents for r in roots):
        raise UnsafePath(f"Refusing to delete {path}: not inside a library folder")
    if not target.exists():
        return False
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return True
