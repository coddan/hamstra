from app.providers import tmdb, tvmaze
from app.services import matching


def test_sim():
    assert matching.sim("Daddys Home", "Daddy's Home") == 1.0
    assert matching.sim("Alien Earth", "Alien: Earth") == 1.0
    assert matching.sim("Zzz", "Completely different") < 0.3


def test_guess_movie_needs_year_to_be_loose(monkeypatch):
    def fake(q, year=None, language="en-US"):
        if q.lower().startswith(("crocile dundee", "dundee")):
            return [{"tmdb_id": 1, "title": "Crocodile Dundee II", "original_title": "Crocodile Dundee II", "year": 1988}]
        if q.lower().startswith("lego batman"):
            return [{"tmdb_id": 2, "title": "LEGO Batman: The Movie - DC Super Heroes Unite", "original_title": "LEGO Batman: The Movie - DC Super Heroes Unite", "year": 2013}]
        return []
    monkeypatch.setattr(tmdb, "search_movies_ext", fake)
    hit, score = matching.guess_movie("Crocile Dundee 2", 1988)                  # typo, year confirms it
    assert hit["tmdb_id"] == 1 and score >= 0.62
    assert matching.guess_movie("Crocile Dundee 2", None)[0]["tmdb_id"] == 1    # 94% similar: fine even without a year
    assert matching.guess_movie("Dundee 2", 1988)[0]["tmdb_id"] == 1            # only ~60% similar: the matching year allows it
    assert matching.guess_movie("Dundee 2", None) is None                       # ...but without a year it does not
    assert matching.guess_movie("LEGO BATMAN 2", 2012) is None                  # 2013 is within a year, but too different


def test_guess_movie_truncates_junk(monkeypatch):
    seen = []

    def fake(q, year=None, language="en-US"):
        seen.append(q)
        return [{"tmdb_id": 3, "title": "Ture Sventon och fallet Isabella", "original_title": "Ture Sventon och fallet Isabella", "year": 1993}] \
            if q == "Ture Sventon och fallet Isabella" else []
    monkeypatch.setattr(tmdb, "search_movies_ext", fake)
    hit, _ = matching.guess_movie("Ture Sventon och fallet Isabella SWESUB extra junk", 1993)
    assert hit["tmdb_id"] == 3 and "Ture Sventon och fallet Isabella" in seen


def test_guess_show_falls_back_to_tmdb_for_swedish(monkeypatch):
    monkeypatch.setattr(tvmaze, "search_shows", lambda q: [])
    monkeypatch.setattr(tmdb, "search_tv", lambda q, language="en-US": [
        {"tmdb_id": 55, "title": "Det var en gång… Rymden", "original_title": "Il était une fois... l'Espace", "year": 1982}]
        if language == "sv-SE" else [])
    monkeypatch.setattr(tmdb, "tv_imdb_id", lambda i: "tt0123456")
    monkeypatch.setattr(tvmaze, "lookup_imdb", lambda imdb: [{"tvmaze_id": 99, "title": "Il était une fois... l'espace", "year": 1982}])
    hit, score = matching.guess_show("Det var en gång - Rymden", None)
    assert hit["tvmaze_id"] == 99 and score == 0.9
    monkeypatch.setattr(tmdb, "search_tv", lambda q, language="en-US": [])
    assert matching.guess_show("Totally Unknown Show", None) is None


def test_guess_show_fuzzy_on_tvmaze(monkeypatch):
    monkeypatch.setattr(tvmaze, "search_shows", lambda q: [{"tvmaze_id": 7, "title": "Star Trek: Lower Decks", "year": 2020}])
    hit, score = matching.guess_show("Star Trek - Lower Decks", None)
    assert hit["tvmaze_id"] == 7 and score > 0.9
    monkeypatch.setattr(tvmaze, "search_shows", lambda q: [{"tvmaze_id": 8, "title": "Something Else Entirely", "year": 2020}])
    monkeypatch.setattr(tmdb, "search_tv", lambda q, language="en-US": [])
    assert matching.guess_show("Star Trek - Lower Decks", None) is None
