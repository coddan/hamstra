import hashlib

import pytest

from app.services.bencode import info_hash


def test_info_hash():
    info = b"d6:lengthi5e4:name1:a12:piece lengthi16384e6:pieces20:" + b"x" * 20 + b"e"
    t = b"d8:announce3:foo4:info" + info + b"e"
    assert info_hash(t) == hashlib.sha1(info).hexdigest()
    with pytest.raises(ValueError):
        info_hash(b"<html>nope</html>")
