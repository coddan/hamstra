from . import archiveorg, hdbits, iptorrents, torznab


def _torznab_download(indexer, url: str) -> bytes:
    import httpx

    r = httpx.get(url, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.content


def _f(name, label, secret=False, required=True, placeholder=""):
    return {"name": name, "label": label, "secret": secret, "required": required, "placeholder": placeholder}


KINDS = {
    "torznab": {
        "label": "Torznab", "default_url": "",
        "fields": [_f("url", "Torznab URL"), _f("api_key", "API key", secret=True, required=False),
                   _f("categories", "Categories", required=False, placeholder="2000,5000")],
        "search": torznab.search, "test": torznab.test_indexer, "download": _torznab_download,
    },
    "rss": {
        "label": "RSS feed", "default_url": "",
        "fields": [_f("url", "Feed URL")],
        "search": torznab.search, "test": torznab.test_indexer, "download": _torznab_download,
    },
    "hdbits": {
        "label": "HDBits", "default_url": "https://hdbits.org",
        "fields": [_f("username", "Username"), _f("api_key", "Passkey", secret=True),
                   _f("categories", "Categories (1=movie, 2=TV)", required=False)],
        "search": hdbits.search, "test": hdbits.test, "download": hdbits.download,
    },
    "archiveorg": {
        "label": "archive.org (free)", "default_url": "https://archive.org",
        "fields": [_f("categories", "Only these media types (empty = any)", required=False, placeholder="audio,movies,texts,software")],
        "search": archiveorg.search, "test": archiveorg.test, "download": archiveorg.download,
    },
    "iptorrents": {
        "label": "IPTorrents", "default_url": "https://iptorrents.com",
        "fields": [_f("url", "Site URL", placeholder="https://iptorrents.com"),
                   _f("cookie", "Cookie (uid, pass, cf_clearance)", secret=True),
                   _f("user_agent", "User agent (must match the browser)", required=False),
                   _f("categories", "Category IDs", required=False)],
        "search": iptorrents.search, "test": iptorrents.test, "download": iptorrents.download,
    },
}


def get(kind: str) -> dict:
    if kind not in KINDS:
        raise ValueError(f"Unknown indexer type: {kind}")
    return KINDS[kind]


def public_kinds() -> list[dict]:
    return [{"kind": k, "label": v["label"], "default_url": v["default_url"], "fields": v["fields"]} for k, v in KINDS.items()]
