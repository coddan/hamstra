import os
from pathlib import Path

from dotenv import dotenv_values

from pydantic_settings import BaseSettings, SettingsConfigDict


def _alias_env() -> None:
    """HAMSTRA_* is the preferred prefix; the older ARR_* names keep working. Values from a .env file are included."""
    for source in (dict(os.environ), dotenv_values(".env")):
        for key, value in source.items():
            if key.startswith("HAMSTRA_") and value is not None:
                os.environ.setdefault("ARR_" + key[len("HAMSTRA_"):], value)


_alias_env()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARR_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    database_url: str | None = None
    api_key: str = "change-me"
    tmdb_api_key: str = ""

    tv_root: Path = Path("/media/tv")
    movies_kids_root: Path = Path("/media/movies/kids")
    movies_adults_root: Path = Path("/media/movies/adults")
    music_root: Path = Path("/media/music")
    downloads_dir: Path = Path("/downloads")

    scheduler_enabled: bool = True
    secure_cookies: bool = False  # set true when the app is served over HTTPS (reverse proxy)
    min_free_gb: float = 20.0  # default for Settings → Downloads; 0 disables the check
    auto_search: bool = False  # periodic search for missing/upgradable items
    import_mode: str = "hardlink"  # hardlink | move | copy

    frontend_dir: Path = Path("../frontend/dist")

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.data_dir / 'arr.db'}"


settings = Settings()
