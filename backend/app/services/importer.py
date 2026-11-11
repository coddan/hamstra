import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Album, Episode, History, Movie, QueueItem, Series
from . import naming, notify, unpack
from .request_notice import mark_available
from .parser import parse

log = logging.getLogger("hamstra.import")
MIN_VIDEO_BYTES = 1  # raise for real use; samples are filtered by name


def find_videos(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in naming.VIDEO_EXT else []
    return sorted(
        (p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in naming.VIDEO_EXT
         and "sample" not in p.name.lower() and p.stat().st_size >= MIN_VIDEO_BYTES),
        key=lambda p: -p.stat().st_size,
    )


def place(src: Path, dest: Path, mode: str) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    if mode == "move":
        size = src.stat().st_size
        shutil.move(src, dest)
        if dest.stat().st_size != size:
            raise OSError(f"move verification failed for {dest.name}: size mismatch")
        return "move"
    if mode == "hardlink":
        try:
            os.link(src, dest)
            return "hardlink"
        except OSError:
            pass
    shutil.copy2(src, dest)
    if dest.stat().st_size != src.stat().st_size:
        dest.unlink(missing_ok=True)
        raise OSError(f"copy verification failed for {dest.name}: size mismatch")
    return "copy"


SUB_EXT = {".srt", ".sub", ".idx", ".ass", ".ssa", ".vtt"}
LANGS = {"swedish": "sv", "swe": "sv", "sv": "sv", "svenska": "sv", "english": "en", "eng": "en", "en": "en",
         "norwegian": "no", "nor": "no", "danish": "da", "dan": "da", "finnish": "fi", "fin": "fi",
         "german": "de", "ger": "de", "french": "fr", "fre": "fr", "spanish": "es", "spa": "es"}


def _lang(name: str) -> str:
    for tok in re.split(r"[^a-z]+", name.lower()):
        if tok in LANGS:
            return LANGS[tok]
    return ""


def copy_subtitles(src_root: Path, video: Path, dest: Path, multiple_videos: bool) -> int:
    """Copy subtitle files that belong to `video` next to `dest`, e.g. `Movie (2010).sv.srt`."""
    if not src_root.is_dir():
        return 0
    keys = naming.parse_episode(video.name)
    copied: set[str] = set()
    count = 0
    for sub in sorted(src_root.rglob("*")):
        if not sub.is_file() or sub.suffix.lower() not in SUB_EXT:
            continue
        if multiple_videos:
            same_ep = bool(keys) and (naming.parse_episode(sub.name) == keys or naming.parse_episode(sub.parent.name) == keys)
            if not (same_ep or sub.stem.startswith(video.stem)):
                continue
        lang = _lang(sub.stem) or _lang(sub.parent.name)
        target = dest.with_name(f"{dest.stem}{'.' + lang if lang else ''}{sub.suffix.lower()}")
        n = 1
        while target.name in copied:
            n += 1
            target = dest.with_name(f"{dest.stem}{'.' + lang if lang else ''}.{n}{sub.suffix.lower()}")
        copied.add(target.name)
        try:
            shutil.copy2(sub, target)
            count += 1
        except OSError as e:
            log.warning("subtitle copy failed for %s: %s", sub.name, e)
    return count


def _remove_old(old: str | None, new: Path):
    if old and Path(old) != new and Path(old).exists():
        Path(old).unlink()


def import_item(db: Session, item: QueueItem, content_path: str | None = None) -> bool:
    try:
        return _import_item(db, item, content_path)
    except (OSError, unpack.UnpackError) as e:
        db.rollback()
        item.status, item.error = "failed", str(e)
        db.add(History(event="failed", title=item.title, detail=item.error))
        db.commit()
        return False


def _import_album(db: Session, item: QueueItem, src_root: Path) -> bool:
    from . import music
    from .music_parser import parse_music, quality_key

    album = db.get(Album, item.album_id)

    def collect(root: Path) -> list[Path]:
        if root.is_file():
            return [root] if root.suffix.lower() in music.KEEP_EXT else []
        return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in music.KEEP_EXT
                      and not any(part.lower() in music.SKIP_DIRS for part in p.relative_to(root).parts))

    files, scratch, base = (collect(src_root) if src_root.exists() else []), None, src_root
    if not any(f.suffix.lower() in music.AUDIO_EXT for f in files) and src_root.is_dir():
        archives = unpack.find_archives(src_root)
        if archives:
            scratch = settings.downloads_dir / ".hamstra-unpack" / str(item.id)
            try:
                for a in archives:
                    unpack.extract(a, scratch)
                files, base = collect(scratch), scratch
            except BaseException:
                shutil.rmtree(scratch, ignore_errors=True)
                raise
    try:
        if not any(f.suffix.lower() in music.AUDIO_EXT for f in files):
            item.status, item.error = "failed", "no audio files found"
            db.add(History(event="failed", title=item.title, detail=item.error))
            db.commit()
            return False
        quality = quality_key(parse_music(item.title), "") or "audio"
        profile = music.get_profile(db)
        if profile.get("layout", "release") == "release":
            # scene-style library: <genre>/<release folder name>, exactly as the release came
            root = music.music_root(db)
            dest_base = Path(root.path) / album.genre if album.genre else Path(root.path)
            dest = dest_base / (music.clean_name(src_root.name if src_root.is_dir() or scratch else src_root.stem) or music.clean_name(item.title))
        else:
            dest = Path(album.path) if album.path else music.target_folder(db, album)[0]
        if dest.exists() and music.has_audio(dest):   # never mix two versions of an album in one folder
            dest = dest.with_name(f"{dest.name} [{quality}]")
        mode = "move" if scratch else settings.import_mode
        used = set()
        for f in files:
            rel = f.name if base.is_file() else str(f.relative_to(base))
            used.add(place(f, dest / rel, mode))
        album.has_files, album.file_format = True, quality
        if not album.path or Path(album.path) != dest:
            album.path = str(dest)
        item.status, item.imported_at = "seeding", datetime.utcnow()
        db.add(History(event="imported", title=item.title,
                       detail=f"method={'/'.join(sorted(used))}, {sum(1 for f in files if f.suffix.lower() in music.AUDIO_EXT)} tracks"
                              + (", unpacked from archive" if scratch else "")))
        db.commit()
        notify.send(db, f"Imported: {item.title}")
        notify.plex_refresh(db, str(dest))
        return True
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)


def _import_item(db: Session, item: QueueItem, content_path: str | None = None) -> bool:
    src_root = Path(content_path or item.save_path or "")
    if item.kind == "album":
        return _import_album(db, item, src_root)
    videos = find_videos(src_root) if src_root.exists() else []
    scratch: Path | None = None
    if not videos and src_root.is_dir():
        archives = unpack.find_archives(src_root)
        if archives:
            scratch = settings.downloads_dir / ".hamstra-unpack" / str(item.id)
            try:
                for a in archives:
                    unpack.extract(a, scratch)
                videos = find_videos(scratch)
            except BaseException:
                shutil.rmtree(scratch, ignore_errors=True)
                raise
    try:
        return _place_and_finish(db, item, videos, scratch, scratch or src_root)
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)


def _place_and_finish(db: Session, item: QueueItem, videos: list[Path], scratch: Path | None, sub_root: Path) -> bool:
    if not videos:
        item.status, item.error = "failed", "no video files found"
        db.add(History(event="failed", title=item.title, detail=item.error))
        db.commit()
        return False

    quality = parse(item.title).resolution
    mode = "move" if scratch else settings.import_mode  # unpacked files are ours: move, don't copy
    used_unpack = bool(scratch)
    used: set[str] = set()
    subs = 0
    upgraded = False

    if item.kind == "movie":
        m = db.get(Movie, item.movie_id)
        video = videos[0]
        folder = Path(m.path or "")
        dest = folder / f"{naming.folder_name(m.title, m.year)}{video.suffix.lower()}"
        upgraded = m.has_file
        used.add(place(video, dest, mode))
        subs += copy_subtitles(sub_root, video, dest, len(videos) > 1)
        _remove_old_movie_files(folder, dest)
        m.has_file, m.file_resolution = True, quality
    else:
        s = db.get(Series, item.series_id)
        wanted = {e.id: e for e in db.query(Episode).filter(Episode.id.in_([int(i) for i in item.episode_ids.split(",") if i]))}
        by_key = {(e.season, e.number): e for e in wanted.values()}
        placed = 0
        for video in videos:
            keys = naming.parse_episode(video.name)
            if not keys:  # daily show: the file is named by air date
                d = naming.parse_air_date(video.name)
                keys = [(e.season, e.number) for e in wanted.values() if d and e.air_date == d]
            for key in keys:
                e = by_key.get(key)
                if not e:
                    continue
                dest = Path(s.path or "") / f"Season {e.season:02d}" / (
                    f"{naming.clean(s.title)} - S{e.season:02d}E{e.number:02d}"
                    f"{' - ' + naming.clean(e.title) if e.title else ''}{video.suffix.lower()}"
                )
                upgraded = upgraded or e.has_file
                used.add(place(video, dest, mode))
                subs += copy_subtitles(sub_root, video, dest, len(videos) > 1)
                _remove_old(e.file_path, dest)
                e.file_path, e.file_resolution = str(dest), quality
                placed += 1
        if not placed:
            item.status, item.error = "failed", "no matching episodes in download"
            db.add(History(event="failed", title=item.title, detail=item.error))
            db.commit()
            return False

    item.status = "seeding"
    item.imported_at = datetime.utcnow()
    db.add(History(event="upgraded" if upgraded else "imported", title=item.title, detail=f"method={'/'.join(sorted(used))}{', unpacked from archive' if used_unpack else ''}{f', {subs} subtitle file(s)' if subs else ''}"))
    db.commit()
    notify.send(db, f"Imported: {item.title}")
    notify.plex_refresh(db, _library_path(db, item))
    mark_available(db, item)
    return True


def _remove_old_movie_files(folder: Path, keep: Path):
    for p in folder.glob("*"):
        if p.is_file() and p != keep and p.suffix.lower() in naming.VIDEO_EXT:
            p.unlink()


def _library_path(db: Session, item: QueueItem) -> str | None:
    if item.kind == "movie":
        m = db.get(Movie, item.movie_id)
        p = Path(m.path) if m and m.path else None
        return str(p.parent if p and p.suffix else p) if p else None
    s = db.get(Series, item.series_id)
    return s.path if s else None
