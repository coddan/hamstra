import json

from sqlalchemy.orm import Session

from ..models import Setting

KEY = "movie_rules"
DEFAULTS = {
    "kids_certifications": ["G", "PG", "TV-Y", "TV-Y7", "TV-G", "Btl", "7", "11", "0", "6"],
    "kids_genres": ["Family", "Animation"],
    "use_genres_when_no_certification": True,
    "default_kind": "movies_adults",  # used when no certification and genre rule is off/not matched
}


def get_rules(db: Session) -> dict:
    row = db.get(Setting, KEY)
    return {**DEFAULTS, **(json.loads(row.value) if row else {})}


def save_rules(db: Session, rules: dict) -> dict:
    merged = {**DEFAULTS, **rules}
    row = db.get(Setting, KEY)
    if row:
        row.value = json.dumps(merged)
    else:
        db.add(Setting(key=KEY, value=json.dumps(merged)))
    db.commit()
    return merged


def pick_movie_kind(rules: dict, certification: str | None, genres: list[str]) -> str:
    if certification:
        kids = certification.strip().upper() in {c.upper() for c in rules["kids_certifications"]}
        return "movies_kids" if kids else "movies_adults"
    if rules["use_genres_when_no_certification"] and set(rules["kids_genres"]) & set(genres):
        return "movies_kids"
    return rules["default_kind"]
