import pytest

from app.services.music_parser import name_matches, parse_music, quality_key

CASES = [
    ("Pink_Floyd-The_Dark_Side_Of_The_Moon-REMASTERED-CD-FLAC-1993-GRP", "flac", None, "cd", 1993),
    ("Metallica - Master of Puppets (1986) [FLAC]", "flac", None, None, 1986),
    ("Iron Maiden - Powerslave [1984] MP3 320 kbps", "mp3", "320", None, 1984),
    ("Artist - Album 2015 MP3 V0", "mp3", "v0", None, 2015),
    ("Artist-Album-WEB-2023-GRP", None, None, "web", 2023),
    ("Artist - Album (Vinyl) 24bit 96kHz FLAC", "flac", None, "vinyl", None),
]


@pytest.mark.parametrize("c", CASES, ids=[c[0] for c in CASES])
def test_parse(c):
    name, fmt, br, src, year = c
    r = parse_music(name)
    assert (r.format, r.bitrate, r.source, r.year) == (fmt, br, src, year)


def test_quality_keys():
    assert quality_key(parse_music("A - B 2001 FLAC")) == "flac"
    assert quality_key(parse_music("A - B 24bit FLAC")) == "flac-24"
    assert quality_key(parse_music("A - B MP3 320")) == "mp3-320"
    assert quality_key(parse_music("A - B MP3")) == "mp3-unknown"
    assert quality_key(parse_music("A-B-WEB-2020-GRP")) is None
    assert quality_key(parse_music("A-B-WEB-2020-GRP"), "Music/Flac") == "flac"      # the tracker category tells
    assert quality_key(parse_music("A - B"), "Music/Audio") is None


def test_name_matching():
    t = "Pink_Floyd-The_Dark_Side_Of_The_Moon-REMASTERED-CD-FLAC-1993-GRP"
    assert name_matches(t, "Pink Floyd", "The Dark Side of the Moon")
    assert name_matches("Pink Floyd - Dark Side Of The Moon [FLAC]", "Pink Floyd", "The Dark Side of the Moon")  # leading "The"
    assert not name_matches("Pink Floyd - The Wall [FLAC]", "Pink Floyd", "The Dark Side of the Moon")
    assert not name_matches("Other Band - The Dark Side Of The Moon", "Pink Floyd", "The Dark Side of the Moon")
    assert name_matches("Simon & Garfunkel - Bridge over Troubled Water", "Simon and Garfunkel", "Bridge over Troubled Water")
