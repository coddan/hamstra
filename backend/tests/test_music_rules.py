from pathlib import Path
from types import SimpleNamespace

from app.indexers.torznab import Result
from app.services import music

ALBUM = SimpleNamespace(artist="Pink Floyd", title="The Dark Side of the Moon", year=1973)
P = {**music.DEFAULTS}


def R(title, seeders=10, size=400_000_000, category="", priority=25):
    return Result(title=title, seeders=seeders, size=size, category=category, priority=priority, info_hash=None)


def test_accept_reject():
    ok = music.evaluate(R("Pink_Floyd-The_Dark_Side_Of_The_Moon-CD-FLAC-1993-GRP"), ALBUM, P)
    assert ok.accepted and ok.quality == "flac"
    assert "not this artist/album" in music.evaluate(R("Pink Floyd - The Wall [FLAC]"), ALBUM, P).reasons
    assert "mp3-128 not allowed" in music.evaluate(R("Pink Floyd - The Dark Side of the Moon MP3 128"), ALBUM, P).reasons
    assert "unknown audio format" in music.evaluate(R("Pink Floyd - The Dark Side of the Moon"), ALBUM, P).reasons
    assert "contains 'live'" in music.evaluate(R("Pink Floyd - The Dark Side of the Moon Live FLAC"), ALBUM, P).reasons
    assert "too large" in music.evaluate(R("Pink Floyd - The Dark Side of the Moon FLAC", size=9_000_000_000), ALBUM, P).reasons
    assert "not enough seeders" in music.evaluate(R("Pink Floyd - The Dark Side of the Moon FLAC", seeders=0), ALBUM, P).reasons
    # category supplies the format when the name has none
    assert music.evaluate(R("Pink Floyd - The Dark Side of the Moon (1973)", category="Music/Flac"), ALBUM, P).accepted
    # "live" in the album's own title is fine
    live = SimpleNamespace(artist="Pink Floyd", title="Live at Pompeii", year=1972)
    assert music.evaluate(R("Pink Floyd - Live at Pompeii FLAC"), live, P).accepted


def test_best_prefers_order_and_words():
    flac = R("Pink Floyd - The Dark Side of the Moon FLAC")
    mp3 = R("Pink Floyd - The Dark Side of the Moon MP3 320", seeders=90)
    assert music.best([mp3, flac], ALBUM, P).result is flac            # profile order beats seeders
    p2 = {**P, "order": ["mp3-320", "flac"]}
    assert music.best([mp3, flac], ALBUM, p2).result is mp3
    p3 = {**P, "prefer_words": "remastered"}
    rem = R("Pink Floyd - The Dark Side of the Moon REMASTERED FLAC", seeders=5)
    assert music.best([flac, rem], ALBUM, p3).result is rem             # same quality: the preferred word decides
    assert music.best([flac, rem], ALBUM, P).result is flac             # without it, more seeders win
    assert music.best([flac], ALBUM, P, blocked={flac.title}) is None


def test_folders(tmp_path):
    root = tmp_path / "musik"
    (root / "¤METAL¤" / "Iron Maiden" / "Powerslave (1984)").mkdir(parents=True)
    (root / "¤METAL¤" / "Iron Maiden" / "Powerslave (1984)" / "01.mp3").write_text("x")
    (root / "¤ROCK¤" / "Pink Floyd").mkdir(parents=True)
    (root / "@eaDir").mkdir()
    assert music.genre_folders(root) == ["¤METAL¤", "¤ROCK¤"]                      # system folders hidden
    assert music.find_artist_dir(root, "Pink Floyd") == root / "¤ROCK¤" / "Pink Floyd"
    assert music.find_existing_album(root, "Iron Maiden", "Powerslave") == root / "¤METAL¤" / "Iron Maiden" / "Powerslave (1984)"
    assert music.find_existing_album(root, "Iron Maiden", "Piece of Mind") is None
    assert music.has_audio(root / "¤METAL¤" / "Iron Maiden" / "Powerslave (1984)")
    assert not music.has_audio(root / "¤ROCK¤" / "Pink Floyd")


def test_archive_items_get_their_real_format(monkeypatch):
    from app.indexers import archiveorg

    r_flac = R("Pink Floyd - The Dark Side of the Moon (Double CD Rip)", category="audio")
    r_flac.guid = "item_flac"
    r_mp3 = R("Pink Floyd - The Dark Side of the Moon (1973)", category="audio")
    r_mp3.guid = "item_mp3"
    r_other = R("Someone Else - Unrelated Album", category="audio")
    r_other.guid = "item_other"
    seen = []
    hints = {"item_flac": "Music/Flac", "item_mp3": "Music/MP3 v2"}
    monkeypatch.setattr(archiveorg, "audio_quality_hint", lambda ident, base=archiveorg.BASE: seen.append(ident) or hints.get(ident))
    music.enrich([r_flac, r_mp3, r_other], ALBUM)
    assert seen == ["item_flac", "item_mp3"]                       # only items whose name matches are looked into
    assert music.evaluate(r_flac, ALBUM, P).quality == "flac" and music.evaluate(r_flac, ALBUM, P).accepted
    assert music.evaluate(r_mp3, ALBUM, P).quality == "mp3-v2"


def test_format_lookup_from_file_list(monkeypatch):
    from app.indexers import archiveorg

    monkeypatch.setattr(archiveorg, "_file_formats", lambda i, b: {"a": ("flac", "vbr mp3"), "b": ("vbr mp3", "ogg vorbis"),
                                                                    "c": ("24bit flac",), "d": ("320kbps mp3",), "e": ("text",)}[i])
    assert [archiveorg.audio_quality_hint(x) for x in "abcde"] == ["Music/Flac", "Music/MP3 v2", "Music/Flac 24bit", "Music/MP3 320", None]


def test_possessive_artist_names():
    from app.services.music_parser import name_matches
    assert name_matches("Pink Floyd's The Wall (1979)", "Pink Floyd", "The Wall")
