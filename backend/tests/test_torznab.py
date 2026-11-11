from app.indexers.torznab import parse_feed

FEED = """<?xml version="1.0"?>
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel>
<item><title>Show.S01E01.1080p.WEB-DL.x264-GRP</title><guid>g1</guid>
<link>https://x/dl/1.torrent</link><enclosure url="https://x/dl/1.torrent" length="1500000000"/>
<pubDate>Tue, 10 Nov 2026 10:00:00 +0000</pubDate>
<torznab:attr name="seeders" value="25"/><torznab:attr name="peers" value="30"/>
<torznab:attr name="infohash" value="ABCDEF0123456789ABCDEF0123456789ABCDEF01"/></item>
<item><title>Movie.2010.1080p</title><guid>g2</guid><link>magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&amp;dn=x</link>
<torznab:attr name="seeders" value="3"/><torznab:attr name="size" value="999"/></item>
<item><title></title></item>
</channel></rss>"""


def test_parse_feed():
    r = parse_feed(FEED, "ix")
    assert len(r) == 2
    assert r[0].seeders == 25 and r[0].size == 1500000000
    assert r[0].info_hash == "abcdef0123456789abcdef0123456789abcdef01"
    assert r[1].download_url.startswith("magnet:")
    assert r[1].info_hash == "0123456789abcdef0123456789abcdef01234567"
    assert r[1].size == 999


def test_error_feed():
    import pytest
    with pytest.raises(ValueError):
        parse_feed('<error code="100" description="Incorrect user credentials"/>')
