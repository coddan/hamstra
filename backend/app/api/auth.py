from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User
from ..services import auth

router = APIRouter(prefix="/api/v1", tags=["auth"])


class Credentials(BaseModel):
    username: str
    password: str


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_SECONDS, httponly=True, samesite="lax", secure=settings.secure_cookies)


def current_user(request: Request, db: Session) -> User | None:
    return auth.user_from_token(db, request.cookies.get(auth.COOKIE) or request.cookies.get(auth.LEGACY_COOKIE))


def is_admin(request: Request, db: Session) -> bool:
    """API-key callers and admin users count as admins; so does anyone when auth is not set up yet."""
    key = request.headers.get("x-api-key")
    if settings.api_key != "change-me" and key == settings.api_key:
        return True
    u = current_user(request, db)
    if u:
        return u.is_admin
    return auth.user_count(db) == 0 and settings.api_key == "change-me"


def require_admin(request: Request, db: Session = Depends(get_db)) -> None:
    if not is_admin(request, db):
        raise HTTPException(403, "Admin only")


@router.get("/auth/status")
def status(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    return {
        "setup_required": auth.user_count(db) == 0,
        "authenticated": bool(u),
        "user": {"id": u.id, "username": u.username, "is_admin": u.is_admin} if u else None,
    }


def _validate(c: Credentials) -> None:
    if not c.username.strip() or len(c.username) > 64:
        raise HTTPException(400, "Username is required")
    if len(c.password) < auth.MIN_PASSWORD:
        raise HTTPException(400, f"Password must be at least {auth.MIN_PASSWORD} characters")


@router.post("/auth/setup")
def setup(body: Credentials, response: Response, db: Session = Depends(get_db)):
    if auth.user_count(db):
        raise HTTPException(409, "Already set up")
    _validate(body)
    u = User(username=body.username.strip(), password_hash=auth.hash_password(body.password), is_admin=True)
    db.add(u)
    db.commit()
    _set_cookie(response, auth.make_token(db, u))
    return {"id": u.id, "username": u.username, "is_admin": True}


@router.post("/auth/login")
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    key = f"{request.client.host if request.client else '?'}:{body.username.lower()}"
    if auth.locked_out(key):
        raise HTTPException(429, "Too many failed attempts, try again in a few minutes")
    u = db.query(User).filter(User.username == body.username.strip()).first()
    if not u or not auth.verify_password(body.password, u.password_hash):
        auth.record_failure(key)
        raise HTTPException(401, "Wrong username or password")
    auth.clear_failures(key)
    _set_cookie(response, auth.make_token(db, u))
    return {"id": u.id, "username": u.username, "is_admin": u.is_admin}


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE)
    response.delete_cookie(auth.LEGACY_COOKIE)
    return {"ok": True}


@router.get("/users", dependencies=[Depends(require_admin)])
def list_users(db: Session = Depends(get_db)):
    return [{"id": u.id, "username": u.username, "is_admin": u.is_admin} for u in db.query(User).order_by(User.username)]


class NewUser(Credentials):
    is_admin: bool = False


@router.post("/users", status_code=201, dependencies=[Depends(require_admin)])
def create_user(body: NewUser, db: Session = Depends(get_db)):
    _validate(body)
    if db.query(User).filter(User.username == body.username.strip()).first():
        raise HTTPException(409, "Username already exists")
    u = User(username=body.username.strip(), password_hash=auth.hash_password(body.password), is_admin=body.is_admin)
    db.add(u)
    db.commit()
    return {"id": u.id, "username": u.username, "is_admin": u.is_admin}


class Password(BaseModel):
    password: str


@router.put("/users/{uid}/password")
def set_password(uid: int, body: Password, request: Request, db: Session = Depends(get_db)):
    me = current_user(request, db)
    if not (is_admin(request, db) or (me and me.id == uid)):
        raise HTTPException(403, "Not allowed")
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    _validate(Credentials(username=u.username, password=body.password))
    u.password_hash = auth.hash_password(body.password)
    db.commit()
    return {"ok": True}


@router.delete("/users/{uid}", status_code=204, dependencies=[Depends(require_admin)])
def delete_user(uid: int, db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    if u.is_admin and db.query(User).filter_by(is_admin=True).count() <= 1:
        raise HTTPException(400, "Cannot delete the last admin")
    db.delete(u)
    db.commit()
