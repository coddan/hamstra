"""Built-in torrent engine on libtorrent. Requires the `libtorrent` package (Python 3.12 image)."""
import threading
import time
from pathlib import Path

import httpx

from .base import TorrentStatus


class LibtorrentEngine:
    def __init__(self, state_dir: Path, port: int = 6881, bind_interface: str | None = None):
        import libtorrent as lt

        self.lt = lt
        self.state_dir = state_dir
        state_dir.mkdir(parents=True, exist_ok=True)
        # Private trackers such as HDBits whitelist clients and reject the stock libtorrent peer id / user agent
        # (the torrent is added but the announce fails). Identify as qBittorrent, which is whitelisted.
        settings = {"listen_interfaces": f"0.0.0.0:{port}", "alert_mask": lt.alert.category_t.error_notification,
                    "user_agent": "qBittorrent/4.6.7", "peer_fingerprint": "-qB4670-", "anonymous_mode": False,
                    # never leave a new download waiting in libtorrent's queue behind many seeding torrents
                    "active_downloads": -1, "active_seeds": -1, "active_limit": -1, "active_checking": 4,
                    "active_dht_limit": -1, "active_tracker_limit": -1, "active_lsd_limit": -1}
        if bind_interface:  # e.g. the VPN interface, prevents leaks
            settings["outgoing_interfaces"] = bind_interface
            settings["listen_interfaces"] = f"{bind_interface}:{port}"
        self.ses = lt.session(settings)
        self.lock = threading.Lock()
        self._load_resume()

    def set_limits(self, down_bps: int, up_bps: int) -> None:
        """Bytes per second for the whole session; 0 means unlimited."""
        with self.lock:
            self.ses.apply_settings({"download_rate_limit": max(0, int(down_bps)), "upload_rate_limit": max(0, int(up_bps))})

    def _load_resume(self):
        for f in self.state_dir.glob("*.resume"):
            try:
                params = self.lt.read_resume_data(f.read_bytes())
                torrent = f.with_suffix(".torrent")  # fallback for resume data saved without the info dict
                if params.ti is None and torrent.exists():
                    params.ti = self.lt.torrent_info(self.lt.bdecode(torrent.read_bytes()))
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

    def save_state(self, wait: float = 0):
        """Write resume data (including the info dict, so a restart does not need the metadata again).
        With wait > 0 it blocks until every torrent has answered, for a clean shutdown."""
        lt = self.lt
        with self.lock:
            pending = 0
            for h in self.ses.get_torrents():
                if h.is_valid() and h.status().has_metadata:
                    h.save_resume_data(lt.torrent_handle.save_info_dict)
                    pending += 1
            deadline = time.monotonic() + wait
            while True:
                for a in self.ses.pop_alerts():
                    if isinstance(a, lt.save_resume_data_alert):
                        (self.state_dir / f"{a.handle.info_hashes().v1}.resume").write_bytes(lt.write_resume_data_buf(a.params))
                        pending -= 1
                    elif isinstance(a, lt.save_resume_data_failed_alert):
                        pending -= 1
                if pending <= 0 or time.monotonic() >= deadline:
                    break
                self.ses.wait_for_alert(200)
