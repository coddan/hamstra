"""Match messy folder names to TMDB movies / TVmaze shows."""
import difflib
import re

from ..providers import tmdb, tvmaze
from .naming import normalize

LANGS = ("en-US", "sv-SE")


def variants(title: str) -> list[str]:
    """Alternative spellings of a folder title worth searching for."""
    t = re.sub(r"\s+", " ", title.replace("_", " ")).strip()
    out = [t]
    no_paren = re.sub(r"\s*\([^)]*\)", "", t).strip()
    out.append(no_paren)
    for part in re.split(r",\s+|\s+-\s+|\s*:\s*", no_paren):
        if len(part) >= 4:
            out.append(part.strip())
    seen, res = set(), []
    for v in out:
        if v and normalize(v) and normalize(v) not in seen:
            seen.add(normalize(v))
            res.append(v)
    return res


def _year_ok(cand_year, year) -> bool:
    return year is None or cand_year is None or abs(cand_year - year) <= 1


def match_movie(title: str, year: int | None) -> dict | None:
    """Return the best TMDB candidate for a folder title or None. Titles in English and Swedish are tried."""
    for v in variants(title):
        key = normalize(v)
        for lang in LANGS:
            tries = [tmdb.search_movies_ext(v, year, lang)] if year else [tmdb.search_movies_ext(v, None, lang)]
            if year and not tries[0]:
                tries.append(tmdb.search_movies_ext(v, None, lang))
            for results in tries:
                for r in results[:5]:
                    if not _year_ok(r["year"], year):
                        continue
                    names = {normalize(r["title"]), normalize(r["original_title"])}
                    if key in names:
                        return r
                    if year and r["year"] == year and len(key) >= 4 and any(n.startswith(key) for n in names):
                        return r  # truncated folder name, confirmed by the year
                    words = set(key.split())
                    if year and r["year"] == year and len(words) >= 2 and any(words <= set(n.split()) for n in names):
                        return r  # every word of the folder name is in the title, confirmed by the year
    return None


def _show_query(v: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", v)).strip()  # TVmaze finds nothing for "Alien - Earth", but finds "Alien Earth"


def match_show(title: str, year: int | None) -> dict | None:
    for v in variants(title):
        key = normalize(re.sub(r"\s*\((?:US|UK|AU|CA|NZ)\)$", "", v, flags=re.I))
        hits = tvmaze.search_shows(_show_query(v))
        for h in hits[:5]:
            names = {normalize(h["title"]), normalize(re.sub(r"\s*\((?:US|UK|AU|CA|NZ)\)$", "", h["title"], flags=re.I))}
            if key in names and _year_ok(h["year"], year):
                return h
    return None


def candidates_movie(title: str, year: int | None, limit: int = 6) -> list[dict]:
    """Ranked TMDB suggestions for a release/folder name (exact title + year first)."""
    found: dict[int, dict] = {}
    for v in variants(title)[:3]:
        key = normalize(v)
        for lang in LANGS:
            for r in tmdb.search_movies_ext(v, year, lang)[:6]:
                if r["tmdb_id"] in found:
                    continue
                names = {normalize(r["title"]), normalize(r["original_title"])}
                score = (2 if key in names else 0) + (1 if year and r["year"] == year else 0)
                found[r["tmdb_id"]] = {**r, "score": score}
    return sorted(found.values(), key=lambda r: -r["score"])[:limit]


def candidates_show(title: str, year: int | None, limit: int = 6) -> list[dict]:
    found: dict[int, dict] = {}
    for v in variants(title)[:3]:
        key = normalize(v)
        for h in tvmaze.search_shows(_show_query(v))[:6]:
            if h["tvmaze_id"] in found:
                continue
            score = (2 if key == normalize(re.sub(r"\s*\((?:US|UK|AU|CA|NZ)\)$", "", h["title"], flags=re.I)) else 0) + \
                    (1 if year and h["year"] == year else 0)
            found[h["tvmaze_id"]] = {**h, "score": score}
    return sorted(found.values(), key=lambda h: -h["score"])[:limit]


# ---------------- best guess (used when the folder decides the type and an exact match failed) ----------------
def sim(a: str, b: str) -> float:
    """Similarity of two titles, 0..1, on normalised text."""
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def _truncations(v: str, year: int | None) -> list[str]:
    words = v.split()
    out = [v]
    if year and len(words) > 2:  # junk after the real title ("... SWESUB 720p"): try shorter prefixes
        out += [" ".join(words[:n]) for n in range(len(words) - 1, max(1, len(words) - 4), -1)]
    return out


def guess_movie(title: str, year: int | None) -> tuple[dict, float] | None:
    best: tuple[dict, float] | None = None
    for v in variants(title)[:3]:
        for q in _truncations(v, year):
            for lang in LANGS:
                for results in ([tmdb.search_movies_ext(q, year, lang)] if year else [tmdb.search_movies_ext(q, None, lang)]):
                    for r in results[:6]:
                        if year and r["year"] and abs(r["year"] - year) > 1:
                            continue
                        s = max(sim(title, r["title"]), sim(title, r["original_title"]), sim(q, r["title"]), sim(q, r["original_title"]))
                        if year and r["year"] == year:
                            s += 0.12
                        if best is None or s > best[1]:
                            best = (r, s)
            if best and best[1] >= 0.95:
                return best
    if not best:
        return None
    need = 0.62 if year else 0.88        # with a year to confirm it we can be looser
    return best if best[1] >= need else None


def _show_from_tmdb(query: str) -> dict | None:
    """Swedish/translated titles: find the show on TMDB, then map it to TVmaze through its IMDb id."""
    for lang in LANGS:
        for r in tmdb.search_tv(query, lang)[:4]:
            if max(sim(query, r["title"]), sim(query, r["original_title"])) >= 0.85:
                imdb = tmdb.tv_imdb_id(r["tmdb_id"])
                hits = tvmaze.lookup_imdb(imdb) if imdb else []
                if hits:
                    return hits[0]
    return None


def guess_show(title: str, year: int | None) -> tuple[dict, float] | None:
    best: tuple[dict, float] | None = None
    for v in variants(title)[:3]:
        for h in tvmaze.search_shows(_show_query(v))[:5]:
            s = max(sim(title, h["title"]), sim(v, h["title"]))
            if year and h["year"] and abs(h["year"] - year) <= 1:
                s += 0.1
            if best is None or s > best[1]:
                best = (h, s)
    if best and best[1] >= 0.75:
        return best
    for v in variants(title)[:3]:                     # TVmaze found nothing similar: ask TMDB (Swedish titles)
        try:
            hit = _show_from_tmdb(v)
        except Exception:
            hit = None
        if hit:
            return hit, 0.9
    return None
