import re
import shutil
import subprocess
from pathlib import Path

ARCHIVE_EXT = {".rar", ".zip", ".7z"}
_LATER_PART = re.compile(r"\.part0*([2-9]|[1-9]\d+)\.rar$", re.I)


class UnpackError(Exception):
    pass


def extractor() -> list[str] | None:
    for name in ("7zz", "7z", "7za"):
        if shutil.which(name):
            return [name, "x", "-y", "-bd", "-bso0", "-bsp0"]
    if shutil.which("unrar"):
        return ["unrar", "x", "-y", "-idq"]
    return None


def find_archives(root: Path) -> list[Path]:
    """First volumes of archives under root (later .partNN.rar / .rNN volumes are read by the extractor)."""
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in ARCHIVE_EXT and not _LATER_PART.search(p.name):
            out.append(p)
    return out


def extract(archive: Path, dest: Path) -> None:
    cmd = extractor()
    if not cmd:
        raise UnpackError("no extractor installed (need 7z or unrar)")
    dest.mkdir(parents=True, exist_ok=True)
    if cmd[0] == "unrar":
        full = [*cmd, str(archive), str(dest) + "/"]
    else:
        full = [*cmd, f"-o{dest}", str(archive)]
    r = subprocess.run(full, capture_output=True, text=True)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip().splitlines()
        detail = " | ".join(msg[-2:]) if msg else f"exit code {r.returncode}"
        if "password" in detail.lower() or "encrypted" in detail.lower():
            detail = "archive is password protected"
        raise UnpackError(f"{archive.name}: {detail}")
