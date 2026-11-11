"""Built-in torrent engine on libtorrent. Requires the `libtorrent` package (Python 3.12 image)."""
import threading
from pathlib import Path

import httpx

from .base import TorrentStatus


class LibtorrentEngine:
    def __init__(self, state_dir: Path, listen_interface: str = "0.0.0.0:6881", bind_interface: str | None = None):
        import libtorrent as lt

        self.lt = lt
        self.state_dir = state_dir
        state_dir.mkdir(parents=True, exist_ok=True)
        settings = {"listen_interfaces": listen_interface, "alert_mask": lt.alert.category_t.error_notification}
        if bind_interface:  # e.g. the VPN interface, prevents leaks
            settings["outgoing_interfaces"] = bind_interface
            settings["listen_interfaces"] = f"{bind_interface}:6881"
        self.ses = lt.session(settings)
        self.lock = threading.Lock()
        self._load_resume()

    def _load_resume(self):
        for f in self.state_dir.glob("*.resume"):
            try:
                params = self.lt.read_resume_data(f.read_bytes())
                self.ses.add_torrent(params)
            except Exception:
                f.unlink(missing_ok=True)

    def add(self, url: str, save_path: str, category: str = "hamstra") -> str | None:
        lt = self.lt
        with self.lock:
            if url.startswith("magnet:"):
                params = lt.parse_magnet_uri(url)
            else:
                r = httpx.get(url, timeout=30, follow_redirects=True)
                r.raise_for_status()
                params = lt.add_torrent_params()
                params.ti = lt.torrent_info(lt.bdecode(r.content))
            params.save_path = save_path
            params.flags &= ~lt.torrent_flags.paused
            handle = self.ses.add_torrent(params)
            return str(handle.info_hashes().v1).lower() if handle.is_valid() else None

    def add_file(self, data: bytes, save_path: str, category: str = "hamstra") -> str | None:
        lt = self.lt
        with self.lock:
            params = lt.add_torrent_params()
            params.ti = lt.torrent_info(lt.bdecode(data))
            params.save_path = save_path
            params.flags &= ~lt.torrent_flags.paused
            handle = self.ses.add_torrent(params)
            return str(handle.info_hashes().v1).lower() if handle.is_valid() else None

    def list(self) -> list[TorrentStatus]:
        out = []
        with self.lock:
            for h in self.ses.get_torrents():
                s = h.status()
                state = ("error" if s.errc.value() else "paused" if (s.flags & self.lt.torrent_flags.paused and not s.flags & self.lt.torrent_flags.auto_managed) else
                         "seeding" if s.is_seeding else "checking" if "checking" in str(s.state) else "downloading")
                down, up = s.all_time_download, s.all_time_upload
                ratio = up / down if down else (up / s.total_wanted if s.total_wanted and s.is_seeding else 0.0)
                secs = s.seeding_duration
                secs = secs.total_seconds() if hasattr(secs, "total_seconds") else secs
                out.append(TorrentStatus(str(s.info_hashes.v1).lower(), s.name, s.progress, state,
                                         str(Path(s.save_path) / s.name), s.download_rate, s.num_seeds, s.total_wanted,
                                         float(ratio), int(secs), s.all_time_upload, s.all_time_download,
                                         s.upload_rate, s.num_peers,
                                         int((s.total_wanted - s.total_wanted_done) / s.download_rate) if s.download_rate > 0 and not s.is_seeding else None))
        return out

    def _find(self, info_hash: str):
        for h in self.ses.get_torrents():
            if str(h.status().info_hashes.v1).lower() == info_hash.lower():
                return h

    def remove(self, info_hash: str, delete_files: bool = False) -> None:
        with self.lock:
            h = self._find(info_hash)
            if h:
                (self.state_dir / f"{info_hash}.resume").unlink(missing_ok=True)
                self.ses.remove_torrent(h, self.lt.session.delete_files if delete_files else 0)

    def pause(self, info_hash: str) -> None:
        with self.lock:
            if h := self._find(info_hash):
                h.unset_flags(self.lt.torrent_flags.auto_managed)
                h.pause()

    def resume(self, info_hash: str) -> None:
        with self.lock:
            if h := self._find(info_hash):
                h.set_flags(self.lt.torrent_flags.auto_managed)
                h.resume()

    def save_state(self):
        with self.lock:
            for h in self.ses.get_torrents():
                if h.is_valid() and h.status().has_metadata:
                    h.save_resume_data()
            for a in self.ses.pop_alerts():
                if isinstance(a, self.lt.save_resume_data_alert):
                    (self.state_dir / f"{a.handle.info_hashes().v1}.resume").write_bytes(
                        self.lt.write_resume_data_buf(a.params))
