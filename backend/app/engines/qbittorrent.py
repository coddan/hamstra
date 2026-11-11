import re

import httpx

from .base import TorrentStatus


class QBittorrent:
    def __init__(self, url: str, username: str = "", password: str = ""):
        self.base = url.rstrip("/")
        self.c = httpx.Client(timeout=20)
        self.auth = (username, password)
        self._logged = False

    def _login(self):
        r = self.c.post(f"{self.base}/api/v2/auth/login", data={"username": self.auth[0], "password": self.auth[1]})
        if r.text.strip() != "Ok.":
            raise RuntimeError("qBittorrent login failed")
        self._logged = True

    def _req(self, method: str, path: str, **kw):
        if not self._logged:
            self._login()
        r = self.c.request(method, f"{self.base}/api/v2{path}", **kw)
        if r.status_code == 403:
            self._login()
            r = self.c.request(method, f"{self.base}/api/v2{path}", **kw)
        r.raise_for_status()
        return r

    def add(self, url: str, save_path: str, category: str = "hamstra") -> str | None:
        self._req("POST", "/torrents/add", data={"urls": url, "savepath": save_path, "category": category})
        m = re.search(r"btih:([0-9a-fA-F]{40})", url)
        return m.group(1).lower() if m else None

    def add_file(self, data: bytes, save_path: str, category: str = "hamstra") -> str | None:
        from ..services.bencode import info_hash

        self._req("POST", "/torrents/add", data={"savepath": save_path, "category": category},
                  files={"torrents": ("file.torrent", data, "application/x-bittorrent")})
        return info_hash(data)

    def list(self) -> list[TorrentStatus]:
        out = []
        for t in self._req("GET", "/torrents/info").json():
            state = t["state"]
            norm = ("error" if "error" in state or state == "missingFiles" else
                    "paused" if state.startswith("paused") or state.startswith("stopped") else
                    "seeding" if t["progress"] >= 1 else "downloading")
            out.append(TorrentStatus(t["hash"].lower(), t["name"], t["progress"], norm,
                                     t.get("content_path") or t["save_path"], t.get("dlspeed", 0),
                                     t.get("num_seeds", 0), t.get("size", 0),
                                     float(t.get("ratio", 0) or 0), int(t.get("seeding_time", 0) or 0),
                                     int(t.get("uploaded", 0) or 0), int(t.get("downloaded", 0) or 0),
                                     int(t.get("upspeed", 0) or 0), int(t.get("num_leechs", 0) or 0),
                                     None if t.get("eta", 8640000) >= 8640000 else int(t["eta"])))
        return out

    def remove(self, info_hash: str, delete_files: bool = False) -> None:
        self._req("POST", "/torrents/delete", data={"hashes": info_hash, "deleteFiles": str(delete_files).lower()})

    def pause(self, info_hash: str) -> None:
        self._req("POST", "/torrents/pause", data={"hashes": info_hash})

    def resume(self, info_hash: str) -> None:
        self._req("POST", "/torrents/resume", data={"hashes": info_hash})
