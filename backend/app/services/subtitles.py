"""Subtitles from OpenSubtitles.com (needs the user's own API key and account). Saved next to the video: 'Movie (2010).sv.srt'."""
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from ..models import Episode, Movie, Series, Setting
from . import naming

log = logging.getLogger("hamstra.subtitles")
API = "https://api.opensubtitles.com/api/v1"
TRIED_KEY = "subtitles_tried"
DEFAULTS = {"enabled": False, "api_key": "", "username": "", "password": "", "languages": "sv,en", "limit_per_run": 5}
SUB_EXT = (".srt", ".ass", ".ssa", ".sub")


class SubtitleError(Exception):
    pass


class QuotaExceeded(SubtitleError):
    pass


def config(db: Session) -> dict:
    row = db.get(Setting, "subtitles")
    return {**DEFAULTS, **(json.loads(row.value) if row else {})}


class OpenSubtitles:
    def __init__(self, api_key: str, username: str, password: str, transport: httpx.BaseTransport | None = None):
        self.c = httpx.Client(transport=transport, timeout=30, headers={
            "Api-Key": api_key, "User-Agent": "Hamstra/1.0", "Content-Type": "application/json", "Accept": "application/json"})
        self.username, self.password, self.token, self.base = username, password, None, API

    def login(self) -> None:
        r = self.c.post(f"{API}/login", json={"username": self.username, "password": self.password})
        if r.status_code in (401, 403):
            raise SubtitleError("OpenSubtitles rejected the API key or the login")
        r.raise_for_status()
        data = r.json()
        self.token = data["token"]
        if data.get("base_url"):
            self.base = f"https://{data['base_url']}/api/v1"

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def search(self, languages: str, imdb_id: str | None = None, season: int | None = None, episode: int | None = None) -> list[dict]:
        params: dict = {"languages": languages, "order_by": "download_count"}
        digits = re.sub(r"\D", "", imdb_id or "")
        if not digits:
            return []
        if season is not None:
            params.update(parent_imdb_id=digits, season_number=season, episode_number=episode, type="episode")
        else:
            params.update(imdb_id=digits, type="movie")
        r = self.c.get(f"{self.base}/subtitles", params=params, headers=self._auth())
        r.raise_for_status()
        return r.json().get("data", [])

    def download(self, file_id: int) -> bytes:
        r = self.c.post(f"{self.base}/download", json={"file_id": file_id, "sub_format": "srt"}, headers=self._auth())
        if r.status_code in (406, 429):
            raise QuotaExceeded("OpenSubtitles download quota reached for today")
        r.raise_for_status()
        link = r.json()["link"]
        f = httpx.get(link, timeout=30, follow_redirects=True)
        f.raise_for_status()
        return f.content


def best(results: list[dict], lang: str) -> int | None:
    """file_id of the most downloaded, non-hearing-impaired subtitle in the wanted language."""
    pool = [r for r in results if r["attributes"].get("language") == lang and r["attributes"].get("files")]
    pool.sort(key=lambda r: (r["attributes"].get("hearing_impaired", False), -(r["attributes"].get("download_count") or 0)))
    return pool[0]["attributes"]["files"][0]["file_id"] if pool else None


def missing_languages(video: Path, languages: list[str]) -> list[str]:
    have = {p.name.lower() for p in video.parent.iterdir() if p.is_file() and p.name.lower().startswith(video.stem.lower() + ".")}
    return [lang for lang in languages if not any(n.startswith(f"{video.stem.lower()}.{lang}.") and n.endswith(SUB_EXT) for n in have)]


def _largest_video(path: str | None) -> Path | None:
    if not path:
        return None
    p = Path(path)
    if p.is_file():
        return p
    vids = [v for v in p.rglob("*") if v.is_file() and v.suffix.lower() in naming.VIDEO_EXT] if p.is_dir() else []
    return max(vids, key=lambda v: v.stat().st_size) if vids else None


def wanted_items(db: Session):
    """(label, video path, imdb id, season, episode) for everything on disk."""
    for m in db.query(Movie).filter(Movie.has_file.is_(True), Movie.imdb_id.isnot(None)):
        v = _largest_video(m.path)
        if v and m.imdb_id:
            yield m.title, v, m.imdb_id, None, None
    for s in db.query(Series).filter(Series.imdb_id.isnot(None)):
        if not s.imdb_id:
            continue
        for e in s.episodes:
            if e.file_path and Path(e.file_path).is_file():
                yield f"{s.title} S{e.season:02d}E{e.number:02d}", Path(e.file_path), s.imdb_id, e.season, e.number


def run(db: Session, client: OpenSubtitles | None = None, limit: int | None = None) -> dict:
    cfg = config(db)
    out = {"downloaded": 0, "not_found": 0, "skipped": 0, "stopped": None}
    if not cfg["enabled"] and client is None:
        return {"disabled": True}
    if not (cfg["api_key"] and cfg["username"] and cfg["password"]):
        return {"error": "Set the API key, username and password under Settings → Subtitles"}
    langs = [x.strip() for x in cfg["languages"].split(",") if x.strip()]
    limit = limit or int(cfg["limit_per_run"])
    row = db.get(Setting, TRIED_KEY)
    tried: dict[str, str] = json.loads(row.value) if row else {}
    cutoff = (datetime.utcnow() - timedelta(days=14)).isoformat()
    client = client or OpenSubtitles(cfg["api_key"], cfg["username"], cfg["password"])
    try:
        client.login()
        for label, video, imdb, season, episode in wanted_items(db):
            for lang in missing_languages(video, langs):
                key = f"{video}|{lang}"
                if tried.get(key, "") > cutoff:
                    out["skipped"] += 1
                    continue
                if out["downloaded"] >= limit:
                    out["stopped"] = "per-run limit reached"
                    raise StopIteration
                fid = best(client.search(lang, imdb, season, episode), lang)
                if fid is None:
                    tried[key] = datetime.utcnow().isoformat()
                    out["not_found"] += 1
                    continue
                (video.parent / f"{video.stem}.{lang}.srt").write_bytes(client.download(fid))
                out["downloaded"] += 1
                log.info("subtitle %s for %s", lang, label)
    except StopIteration:
        pass
    except QuotaExceeded as e:
        out["stopped"] = str(e)
    except SubtitleError as e:
        out["error"] = str(e)
    finally:
        val = json.dumps(tried)
        row = db.get(Setting, TRIED_KEY)
        if row:
            row.value = val
        else:
            db.add(Setting(key=TRIED_KEY, value=val))
        db.commit()
    return out
