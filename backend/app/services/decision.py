from dataclasses import dataclass, field

from ..indexers.torznab import Result
from . import naming
from .parser import Release, parse

DEFAULT_SOURCES = ["remux", "bluray", "web-dl", "webrip", "hdtv", "dvd"]


@dataclass
class Profile:
    allowed: list[int] = field(default_factory=lambda: [720, 1080, 2160])
    cutoff: int = 1080
    min_seeders: int = 1
    max_size_gb_movie: float = 30.0
    max_size_mb_episode: float = 4000.0
    prefer_codec: str | None = "x265"
    sources: list[str] = field(default_factory=lambda: list(DEFAULT_SOURCES))  # allowed
    source_order: list[str] = field(default_factory=lambda: list(DEFAULT_SOURCES))  # best first
    prefer_words: list[str] = field(default_factory=list)
    reject_words: list[str] = field(default_factory=list)
    prefer_hdr: bool = False
    upgrade_allowed: bool = True


@dataclass
class Want:
    kind: str  # movie | episode | season
    title: str
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    current_resolution: int | None = None  # None means nothing on disk
    has_file: bool = False
    episode_count: int = 1  # for season packs: number of episodes wanted
    air_date: object = None  # date of the wanted episode (daily shows are named by date)


@dataclass
class Decision:
    result: Result
    release: Release
    accepted: bool
    reasons: list[str]
    score: float = 0.0


def evaluate(r: Result, want: Want, profile: Profile, blocked: set[str] = frozenset()) -> Decision:
    title_l = r.title.lower()
    rel = parse(r.title)
    why: list[str] = []

    if r.info_hash and r.info_hash in blocked or r.title in blocked:
        why.append("blocklisted")
    if naming.normalize(rel.title) != naming.normalize(want.title):
        why.append("title mismatch")
    if want.kind == "movie":
        if rel.is_tv:
            why.append("is a TV release")
        if want.year and rel.year and rel.year != want.year:
            why.append("year mismatch")
        if r.size and r.size > profile.max_size_gb_movie * 1e9:
            why.append("too large")
    else:
        if not rel.is_tv:
            why.append("not a TV release")
        elif rel.air_date is not None:
            if want.kind != "episode" or rel.air_date != want.air_date:
                why.append("wrong air date")
        elif rel.season != want.season:
            why.append("wrong season")
        elif rel.season_end and rel.season_end != rel.season:
            why.append("multi-season pack")
        elif want.kind == "season" and not rel.season_pack:
            why.append("not a season pack")
        elif want.kind == "episode" and rel.season_pack:
            why.append("season pack")
        elif want.kind == "episode" and want.episode not in rel.episodes:
            why.append("wrong episode")
        limit = profile.max_size_mb_episode * 1e6 * (want.episode_count if want.kind == "season" else 1)
        if r.size and r.size > limit:
            why.append("too large")

    if rel.resolution is None:
        why.append("unknown resolution")
    elif rel.resolution not in profile.allowed:
        why.append(f"{rel.resolution}p not allowed")
    if rel.source == "cam":
        why.append("cam/telesync")
    elif rel.source and rel.source not in profile.sources:
        why.append(f"{rel.source} not allowed")
    for w in profile.reject_words:
        if w and w in title_l:
            why.append(f"contains '{w}'")
            break
    if r.seeders < profile.min_seeders:
        why.append("not enough seeders")

    if want.has_file and not why and not profile.upgrade_allowed:
        why.append("upgrades disabled")
    if want.has_file and not why:
        cur = want.current_resolution or 0
        if cur >= profile.cutoff:
            why.append("cutoff already met")
        elif (rel.resolution or 0) <= cur:
            why.append("not an upgrade")

    score = 0.0
    if rel.resolution:
        score += rel.resolution / 10
    order = profile.source_order
    if rel.source in order:
        score += (len(order) - order.index(rel.source)) * 10
    else:
        score += 10  # unknown source: ranked low but not rejected
    score += 20 * sum(1 for w in profile.prefer_words if w and w in title_l)
    if profile.prefer_hdr and rel.hdr:
        score += 15
    score += (50 - min(max(r.priority, 1), 50)) * 0.2  # indexer priority: tie-breaker, lower number wins
    if profile.prefer_codec and rel.codec == profile.prefer_codec:
        score += 15
    score += 10 * (rel.proper or rel.repack)
    score += min(r.seeders, 100) / 5
    return Decision(r, rel, not why, why, score)


def best(results: list[Result], want: Want, profile: Profile, blocked: set[str] = frozenset()) -> Decision | None:
    ok = [d for d in (evaluate(r, want, profile, blocked) for r in results) if d.accepted]
    return max(ok, key=lambda d: d.score) if ok else None
