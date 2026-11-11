from dataclasses import dataclass
from typing import Protocol


@dataclass
class TorrentStatus:
    info_hash: str
    name: str
    progress: float  # 0..1
    state: str  # downloading | seeding | paused | error | checking | queued
    save_path: str
    download_rate: int = 0
    seeders: int = 0
    size: int = 0
    ratio: float = 0.0
    seeding_seconds: int = 0
    uploaded: int = 0
    downloaded: int = 0
    upload_rate: int = 0
    peers: int = 0
    eta: int | None = None

    @property
    def complete(self) -> bool:
        return self.progress >= 1.0


class Engine(Protocol):
    def add(self, url: str, save_path: str, category: str = "hamstra") -> str | None: ...
    def add_file(self, data: bytes, save_path: str, category: str = "hamstra") -> str | None: ...
    def list(self) -> list[TorrentStatus]: ...
    def remove(self, info_hash: str, delete_files: bool = False) -> None: ...
    def pause(self, info_hash: str) -> None: ...
    def resume(self, info_hash: str) -> None: ...
