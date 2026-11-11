import pytest

from app.services.parser import parse

# (name, title, year, season, episodes, season_pack, resolution, source, codec, group)
CASES = [
    ("The.Matrix.1999.1080p.BluRay.x264-GROUP", "The Matrix", 1999, None, [], False, 1080, "bluray", "x264", "GROUP"),
    ("Shrek.2001.2160p.UHD.BluRay.x265.HDR-RARBG", "Shrek", 2001, None, [], False, 2160, "bluray", "x265", "RARBG"),
    ("Blade Runner 2049 (2017) 720p WEB-DL H264", "Blade Runner 2049", 2017, None, [], False, 720, "web-dl", "x264", None),
    ("2001.A.Space.Odyssey.1968.1080p.BluRay.x264-YIFY", "2001 A Space Odyssey", 1968, None, [], False, 1080, "bluray", "x264", "YIFY"),
    ("The.Office.US.S02E03.720p.HDTV.x264-LOL", "The Office US", None, 2, [3], False, 720, "hdtv", "x264", "LOL"),
    ("Show.Name.S01E02E03.1080p.WEB-DL.DDP5.1.H.264-NTb", "Show Name", None, 1, [2, 3], False, 1080, "web-dl", "x264", "NTb"),
    ("Show.Name.S01E01-E04.1080p.WEBRip.x265-ION10", "Show Name", None, 1, [1, 2, 3, 4], False, 1080, "webrip", "x265", "ION10"),
    ("Show.Name.S03.1080p.BluRay.x264-GRP", "Show Name", None, 3, [], True, 1080, "bluray", "x264", "GRP"),
    ("Show Name Season 2 720p WEB-DL", "Show Name", None, 2, [], True, 720, "web-dl", None, None),
    ("Show.Name.2x05.HDTV.XviD-FoV", "Show Name", None, 2, [5], False, None, "hdtv", "xvid", "FoV"),
    ("Show.Name.2020.S01E05.1080p.AMZN.WEB-DL.x265-GRP", "Show Name", 2020, 1, [5], False, 1080, "web-dl", "x265", "GRP"),
    ("Movie.Title.2010.REPACK.1080p.BluRay.x264-GRP", "Movie Title", 2010, None, [], False, 1080, "bluray", "x264", "GRP"),
]


@pytest.mark.parametrize("c", CASES, ids=[c[0] for c in CASES])
def test_parse(c):
    name, title, year, season, eps, pack, res, src, codec, group = c
    r = parse(name)
    assert (r.title, r.year, r.season, r.episodes, r.season_pack, r.resolution, r.source, r.codec, r.group) == (
        title, year, season, eps, pack, res, src, codec, group)


def test_flags():
    assert parse("Movie.2010.PROPER.1080p.BluRay.x264-G").proper
    assert parse("Movie.2010.REPACK.1080p.BluRay.x264-G").repack
    assert parse("Movie.2010.2160p.WEB-DL.DV.HDR.x265-G").hdr
    assert parse("Movie.2010.1080p.mkv").is_tv is False


def test_daily_show_dates():
    from datetime import date

    r = parse("The.Daily.Show.2026.11.10.Guest.Name.720p.WEB.h264-GRP")
    assert (r.title, r.air_date, r.year, r.season, r.is_tv) == ("The Daily Show", date(2026, 11, 10), None, None, True)
    assert parse("Late Show 2026-01-05 1080p HDTV").air_date == date(2026, 1, 5)
    assert parse("Show.Name.S01E02.2026.mkv").air_date is None                    # a proper SxxExx wins over a year
    assert parse("Some.Movie.2010.1080p.BluRay.x264-G").air_date is None
    assert parse("Odd.2026.13.45.720p").air_date is None                           # impossible date
