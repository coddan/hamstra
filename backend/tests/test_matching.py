from app.providers import tmdb, tvmaze
from app.services import matching


def fake_movies(query, year=None, language="en-US"):
    db = {
        ("Kejsarens nya stil", "sv-SE"): [{"tmdb_id": 1, "title": "Kejsarens nya stil", "original_title": "The Emperor's New Groove", "year": 2000}],
        ("Ed Wo", "en-US"): [{"tmdb_id": 2, "title": "Ed Wood", "original_title": "Ed Wood", "year": 1994}],
        ("Wreck-It Ralph", "en-US"): [{"tmdb_id": 3, "title": "Wreck-It Ralph", "original_title": "Wreck-It Ralph", "year": 2012}],
        ("Queen Of The Damned", "en-US"): [{"tmdb_id": 4, "title": "Queen of the Damned", "original_title": "Queen of the Damned", "year": 2002}],
        ("Alien", "en-US"): [{"tmdb_id": 5, "title": "Alien", "original_title": "Alien", "year": 1979}],
    }
    return db.get((query, language), [])


def test_movie_matching(monkeypatch):
    monkeypatch.setattr(tmdb, "search_movies_ext", fake_movies)
    assert matching.match_movie("Kejsarens nya stil", 2000)["tmdb_id"] == 1          # Swedish title
    assert matching.match_movie("Ed Wo", 1994)["tmdb_id"] == 2                       # truncated + year
    assert matching.match_movie("Ed Wo", None) is None                               # no year: no guessing
    assert matching.match_movie("Wreck-It Ralph (Rojar Ralf)", 2012)["tmdb_id"] == 3  # extra text in parentheses
    assert matching.match_movie("Queen Of The Damned, De Fördömdas Drottning", 2002)["tmdb_id"] == 4
    assert matching.match_movie("Alien", 2017) is None                               # wrong year is rejected


def test_show_matching(monkeypatch):
    seen = []

    def fake(q):
        seen.append(q)
        return [{"tvmaze_id": 9, "title": "Alien: Earth", "year": 2025}] if q == "Alien Earth" else []
    monkeypatch.setattr(tvmaze, "search_shows", fake)
    assert matching.match_show("Alien - Earth", None)["tvmaze_id"] == 9
    assert "Alien Earth" in seen
    assert matching.match_show("Something Else", None) is None


def test_variants():
    v = matching.variants("Queen Of The Damned, De Fördömdas Drottning")
    assert "Queen Of The Damned" in v and v[0].startswith("Queen Of The Damned, De")
    assert matching.variants("Ture_Sventon_i_London")[0] == "Ture Sventon i London"


def test_normalize_apostrophes_and_roman():
    from app.services.naming import normalize

    assert normalize("Daddy's Home") == normalize("Daddys Home") == "daddys home"
    assert normalize("Crocodile Dundee II") == normalize("Crocodile Dundee 2")
    assert normalize("I Robot") == "i robot"            # a leading numeral-like word is left alone
    assert normalize("Rocky IV") == "rocky 4"


def test_word_subset_with_year(monkeypatch):
    monkeypatch.setattr(tmdb, "search_movies_ext", lambda q, y=None, language="en-US": [
        {"tmdb_id": 11, "title": "Halloween: The Curse of Michael Myers", "original_title": "Halloween: The Curse of Michael Myers", "year": 1995}]
        if q.startswith("Halloween") else [])
    assert matching.match_movie("Halloween Curse Michael Myers", 1995)["tmdb_id"] == 11
    assert matching.match_movie("Halloween 6", 1995) is None      # '6' is not in the title: left for a human


def test_swedish_junk_words_are_stripped():
    from app.services.parser import parse
    assert parse("Brisby.och.Nimhs.Hemlighet.svenska.AAC.H264.mkv-DIAF").title == "Brisby och Nimhs Hemlighet"


def test_leading_the_is_ignored():
    from app.services.naming import normalize

    assert normalize("The Simpsons") == normalize("Simpsons") == "simpsons"
    assert normalize("The Matrix Reloaded") == "matrix reloaded"
    assert normalize("The") == "the"                      # a title that is only "The" stays
