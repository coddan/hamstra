import hashlib


def _decode(data: bytes, i: int = 0):
    c = data[i:i + 1]
    if c == b"i":
        j = data.index(b"e", i)
        return int(data[i + 1:j]), j + 1
    if c == b"l":
        i, out = i + 1, []
        while data[i:i + 1] != b"e":
            v, i = _decode(data, i)
            out.append(v)
        return out, i + 1
    if c == b"d":
        i, out = i + 1, {}
        while data[i:i + 1] != b"e":
            k, i = _decode(data, i)
            start = i
            v, i = _decode(data, i)
            if k == b"info":
                out["__info_raw__"] = data[start:i]
            out[k] = v
        return out, i + 1
    j = data.index(b":", i)
    n = int(data[i:j])
    return data[j + 1:j + 1 + n], j + 1 + n


def info_hash(torrent: bytes) -> str:
    """SHA-1 info hash of a .torrent file (raises ValueError if it isn't one)."""
    try:
        d, _ = _decode(torrent)
        return hashlib.sha1(d["__info_raw__"]).hexdigest()
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ValueError("not a valid .torrent file") from e


def torrent_name(torrent: bytes) -> str:
    """Display name stored in a .torrent file (raises ValueError if it isn't one)."""
    try:
        d, _ = _decode(torrent)
        return d[b"info"][b"name"].decode("utf-8", "replace")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
        raise ValueError("not a valid .torrent file") from e
