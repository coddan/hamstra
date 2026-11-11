from app.indexers.torznab import Result
from app.services.decision import Profile, Want, best, evaluate

P = Profile()
MOVIE = Want("movie", "The Matrix", 1999)
EP = Want("episode", "Show Name", season=1, episode=2)


def R(title, seeders=10, size=2_000_000_000, h=None):
    return Result(title=title, seeders=seeders, size=size, info_hash=h, download_url="magnet:x")


def test_movie_accept_and_reject():
    assert evaluate(R("The.Matrix.1999.1080p.BluRay.x264-G"), MOVIE, P).accepted
    assert "year mismatch" in evaluate(R("The.Matrix.2003.1080p.BluRay.x264-G"), MOVIE, P).reasons
    assert "title mismatch" in evaluate(R("The.Matrix.Reloaded.1999.1080p.BluRay.x264-G"), MOVIE, P).reasons
    assert "too large" in evaluate(R("The.Matrix.1999.1080p.BluRay.x264-G", size=40_000_000_000), MOVIE, P).reasons
    assert "cam/telesync" in evaluate(R("The.Matrix.1999.1080p.CAM.x264-G"), MOVIE, P).reasons
    assert "not enough seeders" in evaluate(R("The.Matrix.1999.1080p.BluRay.x264-G", seeders=0), MOVIE, P).reasons
    assert "480p not allowed" in evaluate(R("The.Matrix.1999.480p.DVDRip.x264-G"), MOVIE, P).reasons


def test_episode_matching():
    assert evaluate(R("Show.Name.S01E02.1080p.WEB-DL.x264-G", size=800_000_000), EP, P).accepted
    assert "wrong episode" in evaluate(R("Show.Name.S01E03.1080p.WEB-DL.x264-G"), EP, P).reasons
    assert "wrong season" in evaluate(R("Show.Name.S02E02.1080p.WEB-DL.x264-G"), EP, P).reasons


def test_best_prefers_quality_and_blocklist():
    a = R("The.Matrix.1999.720p.HDTV.x264-G", h="a")
    b = R("The.Matrix.1999.1080p.BluRay.x265-G", h="b")
    assert best([a, b], MOVIE, P).result is b
    assert best([a, b], MOVIE, P, blocked={"b"}).result is a
    assert best([b], MOVIE, P, blocked={"b"}) is None


def test_upgrade_rules():
    have720 = Want("movie", "The Matrix", 1999, current_resolution=720, has_file=True)
    have1080 = Want("movie", "The Matrix", 1999, current_resolution=1080, has_file=True)
    r1080 = R("The.Matrix.1999.1080p.BluRay.x264-G")
    assert evaluate(r1080, have720, P).accepted
    assert "cutoff already met" in evaluate(r1080, have1080, P).reasons


def test_season_packs():
    from app.services.parser import parse

    pack = Want("season", "Show Name", season=1, episode_count=10)
    ok = evaluate(R("Show.Name.S01.1080p.WEB-DL.x264-G", size=15_000_000_000), pack, P)
    assert ok.accepted
    assert "multi-season pack" in evaluate(R("Show.Name.S01-S05.1080p.WEB-DL.x264-G"), pack, P).reasons
    assert "not a season pack" in evaluate(R("Show.Name.S01E02.1080p.WEB-DL.x264-G"), pack, P).reasons
    assert "wrong season" in evaluate(R("Show.Name.S02.1080p.WEB-DL.x264-G"), pack, P).reasons
    assert "too large" in evaluate(R("Show.Name.S01.1080p.WEB-DL.x264-G", size=60_000_000_000), pack, P).reasons
    # episode wants never accept packs
    assert "season pack" in evaluate(R("Show.Name.S01.1080p.WEB-DL.x264-G"), EP, P).reasons
    assert parse("Show.Name.S01.S02.720p").season_end == 2


def test_daily_show_matching():
    from datetime import date

    want = Want("episode", "The Daily Show", season=2026, episode=45, air_date=date(2026, 11, 10))
    ok = evaluate(R("The.Daily.Show.2026.11.10.Guest.720p.WEB.h264-GRP", size=500_000_000), want, P)
    assert ok.accepted
    assert "wrong air date" in evaluate(R("The.Daily.Show.2026.11.11.Guest.720p.WEB.h264-GRP"), want, P).reasons
    assert not evaluate(R("The.Daily.Show.2026.11.10.720p.WEB.h264-GRP"), Want("movie", "The Daily Show"), P).accepted   # a movie want never takes a dated episode
