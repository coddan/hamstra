from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class RootFolder(Base):
    __tablename__ = "root_folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str] = mapped_column(String)  # tv | movies_kids | movies_adults


class QualityProfile(Base):
    __tablename__ = "quality_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    cutoff: Mapped[int] = mapped_column(Integer, default=1080)
    allowed: Mapped[str] = mapped_column(String, default="720,1080,2160")  # resolutions
    min_seeders: Mapped[int] = mapped_column(Integer, default=1)
    max_size_gb_movie: Mapped[float] = mapped_column(default=30.0)
    max_size_mb_episode: Mapped[float] = mapped_column(default=4000.0)
    prefer_codec: Mapped[str | None] = mapped_column(String, default="x265")
    sources: Mapped[str] = mapped_column(String, default="remux,bluray,web-dl,webrip,hdtv,dvd")  # allowed
    source_order: Mapped[str] = mapped_column(String, default="remux,bluray,web-dl,webrip,hdtv,dvd")  # best first
    prefer_words: Mapped[str] = mapped_column(String, default="")
    reject_words: Mapped[str] = mapped_column(String, default="")
    prefer_hdr: Mapped[bool] = mapped_column(Boolean, default=False)
    upgrade_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class Movie(Base):
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, unique=True)
    title: Mapped[str] = mapped_column(String)
    year: Mapped[int | None] = mapped_column(Integer)
    overview: Mapped[str | None] = mapped_column(Text)
    poster_url: Mapped[str | None] = mapped_column(String)
    certification: Mapped[str | None] = mapped_column(String)
    imdb_id: Mapped[str | None] = mapped_column(String)
    release_date: Mapped[datetime | None] = mapped_column(Date)
    monitored: Mapped[bool] = mapped_column(Boolean, default=True)
    path: Mapped[str | None] = mapped_column(String)
    has_file: Mapped[bool] = mapped_column(Boolean, default=False)
    file_resolution: Mapped[int | None] = mapped_column(Integer)
    root_folder_id: Mapped[int | None] = mapped_column(ForeignKey("root_folders.id"))
    quality_profile_id: Mapped[int | None] = mapped_column(ForeignKey("quality_profiles.id"))
    added: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    root_folder: Mapped[RootFolder | None] = relationship()


class Series(Base):
    __tablename__ = "series"

    id: Mapped[int] = mapped_column(primary_key=True)
    tvmaze_id: Mapped[int] = mapped_column(Integer, unique=True)
    title: Mapped[str] = mapped_column(String)
    year: Mapped[int | None] = mapped_column(Integer)
    overview: Mapped[str | None] = mapped_column(Text)
    poster_url: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)
    imdb_id: Mapped[str | None] = mapped_column(String)
    tvdb_id: Mapped[int | None] = mapped_column(Integer)
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime)
    monitored: Mapped[bool] = mapped_column(Boolean, default=True)
    absolute_numbering: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")  # releases are named "Show - 137"
    path: Mapped[str | None] = mapped_column(String)
    root_folder_id: Mapped[int | None] = mapped_column(ForeignKey("root_folders.id"))
    quality_profile_id: Mapped[int | None] = mapped_column(ForeignKey("quality_profiles.id"))
    added: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    episodes: Mapped[list["Episode"]] = relationship(
        back_populates="series", cascade="all, delete-orphan", order_by="Episode.season, Episode.number"
    )


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("series_id", "season", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id"))
    season: Mapped[int] = mapped_column(Integer)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String)
    air_date: Mapped[datetime | None] = mapped_column(Date)
    monitored: Mapped[bool] = mapped_column(Boolean, default=True)
    file_path: Mapped[str | None] = mapped_column(String)
    file_resolution: Mapped[int | None] = mapped_column(Integer)

    series: Mapped[Series] = relationship(back_populates="episodes")

    @property
    def has_file(self) -> bool:
        return bool(self.file_path)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # JSON


class Indexer(Base):
    __tablename__ = "indexers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str] = mapped_column(String, default="torznab")  # torznab | rss
    url: Mapped[str] = mapped_column(String)
    api_key: Mapped[str] = mapped_column(String, default="")
    categories: Mapped[str] = mapped_column(String, default="")  # comma-separated
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=25)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String)
    disabled_until: Mapped[datetime | None] = mapped_column(DateTime)
    username: Mapped[str] = mapped_column(String, default="")
    cookie: Mapped[str] = mapped_column(String, default="")
    user_agent: Mapped[str] = mapped_column(String, default="")
    seed_ratio: Mapped[float | None] = mapped_column()
    seed_hours: Mapped[float | None] = mapped_column()


class QueueItem(Base):
    __tablename__ = "queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String)
    info_hash: Mapped[str | None] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)  # movie | episode
    movie_id: Mapped[int | None] = mapped_column(ForeignKey("movies.id"))
    series_id: Mapped[int | None] = mapped_column(ForeignKey("series.id"))
    episode_ids: Mapped[str] = mapped_column(String, default="")  # comma-separated
    status: Mapped[str] = mapped_column(String, default="downloading")  # downloading|completed|imported|failed
    progress: Mapped[float] = mapped_column(default=0.0)
    save_path: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(String)
    indexer: Mapped[str | None] = mapped_column(String)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime)
    progress_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # engine counters reset when the container restarts, so totals are accumulated here
    album_id: Mapped[int | None] = mapped_column(ForeignKey("albums.id"))
    uploaded_base: Mapped[int] = mapped_column(BigInteger, default=0)
    uploaded_last: Mapped[int] = mapped_column(BigInteger, default=0)
    seed_base: Mapped[int] = mapped_column(BigInteger, default=0)
    seed_last: Mapped[int] = mapped_column(BigInteger, default=0)
    added: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class History(Base):
    __tablename__ = "history"

    id: Mapped[int] = mapped_column(primary_key=True)
    event: Mapped[str] = mapped_column(String)  # grabbed | imported | failed | upgraded
    title: Mapped[str] = mapped_column(String)
    detail: Mapped[str | None] = mapped_column(Text)
    date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Blocklist(Base):
    __tablename__ = "blocklist"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String, index=True)
    info_hash: Mapped[str | None] = mapped_column(String, index=True)
    reason: Mapped[str | None] = mapped_column(String)
    date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String)  # movie | series
    external_id: Mapped[int] = mapped_column(Integer)  # tmdb_id or tvmaze_id
    title: Mapped[str] = mapped_column(String)
    year: Mapped[int | None] = mapped_column(Integer)
    poster_url: Mapped[str | None] = mapped_column(String)
    overview: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | approved | denied
    note: Mapped[str | None] = mapped_column(String)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship()


class Album(Base):
    __tablename__ = "albums"

    id: Mapped[int] = mapped_column(primary_key=True)
    mbid: Mapped[str] = mapped_column(String, unique=True)  # MusicBrainz release-group id
    artist: Mapped[str] = mapped_column(String)
    artist_mbid: Mapped[str | None] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    year: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str | None] = mapped_column(String)  # Album | EP | Single | Compilation ...
    cover_url: Mapped[str | None] = mapped_column(String)
    monitored: Mapped[bool] = mapped_column(Boolean, default=True)
    has_files: Mapped[bool] = mapped_column(Boolean, default=False)
    file_format: Mapped[str | None] = mapped_column(String)  # best quality seen: flac, mp3-320, ...
    genre: Mapped[str] = mapped_column(String, default="")  # folder below the music root, e.g. "¤METAL¤"
    path: Mapped[str | None] = mapped_column(String)
    root_folder_id: Mapped[int | None] = mapped_column(ForeignKey("root_folders.id"))
    added: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
