import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import activity, rootfolders, music as music_api, others, torrents as torrents_api, requests as requests_api, profiles, auth as auth_api, indexers, library, movies, series, settings as settings_api, system
from . import logbuf, scheduler
from .config import settings
from .db import SessionLocal
from .migrate import run_migrations
from .services import auth, queue
from .models import QualityProfile, RootFolder


def seed():
    with SessionLocal() as db:
        if not db.query(RootFolder).count():
            db.add_all(
                [
                    RootFolder(path=str(settings.tv_root), kind="tv"),
                    RootFolder(path=str(settings.movies_kids_root), kind="movies_kids"),
                    RootFolder(path=str(settings.movies_adults_root), kind="movies_adults"),
                ]
            )
        if not db.query(RootFolder).filter_by(kind="music").first():
            db.add(RootFolder(path=str(settings.music_root), kind="music"))
        if not db.query(QualityProfile).count():
            db.add(QualityProfile(name="HD-1080p", is_default=True))
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logbuf.install()
    run_migrations()
    queue.reset_stuck()
    seed()
    sch = scheduler.start() if settings.scheduler_enabled else None
    yield
    if sch:
        sch.shutdown(wait=False)


app = FastAPI(title="Hamstra", version="0.1.0", lifespan=lifespan)
app.include_router(auth_api.router)
app.include_router(system.router)
app.include_router(movies.router)
app.include_router(series.router)
app.include_router(library.router)
app.include_router(settings_api.router)
app.include_router(indexers.router)
app.include_router(profiles.router)
app.include_router(activity.router)
app.include_router(others.router)
app.include_router(rootfolders.router)
app.include_router(music_api.router)
app.include_router(torrents_api.router)
app.include_router(requests_api.router)


USER_READ = ("/api/v1/movies", "/api/v1/series", "/api/v1/calendar", "/api/v1/queue", "/api/v1/history",
             "/api/v1/requests", "/api/v1/profiles", "/api/v1/system/status", "/api/v1/system/vpn", "/api/v1/auth/")


def _allowed_for_user(request: Request, user_id: int) -> bool:
    """Non-admins browse the library, see downloads and make requests; nothing else."""
    path, method = request.url.path, request.method
    if path.startswith("/api/v1/auth/"):
        return True
    if method == "POST" and path == "/api/v1/requests":
        return True
    if method == "DELETE" and path.startswith("/api/v1/requests/"):
        return True  # the endpoint checks ownership
    if method == "PUT" and path == f"/api/v1/users/{user_id}/password":
        return True
    if method in ("GET", "HEAD"):
        # lookup endpoints search external databases; they are needed to find something to request
        return path.startswith(USER_READ) and "/releases" not in path
    return False


PUBLIC = {"/api/health", "/api/v1/auth/status", "/api/v1/auth/login", "/api/v1/auth/logout"}


@app.middleware("http")
async def require_auth(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path in PUBLIC:
        return await call_next(request)
    with SessionLocal() as db:
        has_users = auth.user_count(db) > 0
        if not has_users and settings.api_key == "change-me":
            return await call_next(request)  # nothing configured yet: open until first-run setup
        if path == "/api/v1/auth/setup" and not has_users:
            return await call_next(request)
        key = request.headers.get("x-api-key") or request.query_params.get("apikey")
        if key and settings.api_key != "change-me" and hmac.compare_digest(key, settings.api_key):
            return await call_next(request)
        user = auth.user_from_token(db, request.cookies.get(auth.COOKIE) or request.cookies.get(auth.LEGACY_COOKIE))
        if user:
            if not user.is_admin and not _allowed_for_user(request, user.id):
                return JSONResponse({"detail": "Admins only"}, status_code=403)
            return await call_next(request)
    return JSONResponse({"detail": "Authentication required"}, status_code=401)


@app.get("/api/health")
def health():
    return {"ok": True}


dist = settings.frontend_dir
if dist.is_dir():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        f = dist / path
        target = f if path and f.is_file() else dist / "index.html"
        headers = {"Cache-Control": "no-cache"} if target.name == "index.html" else None
        return FileResponse(target, headers=headers)
