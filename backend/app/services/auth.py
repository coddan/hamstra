import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict

from sqlalchemy.orm import Session

from ..models import Setting, User

COOKIE = "hamstra_session"
LEGACY_COOKIE = "arr_session"  # still accepted
SESSION_SECONDS = 30 * 24 * 3600
MIN_PASSWORD = 8


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc.hex(), h)
    except ValueError:
        return False


def _secret(db: Session) -> bytes:
    row = db.get(Setting, "session_secret")
    if not row:
        row = Setting(key="session_secret", value=json.dumps(secrets.token_hex(32)))
        db.add(row)
        db.commit()
    return json.loads(row.value).encode()


def make_token(db: Session, user: User) -> str:
    payload = f"{user.id}.{int(time.time()) + SESSION_SECONDS}"
    sig = hmac.new(_secret(db), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode()


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    try:
        uid, exp, sig = base64.urlsafe_b64decode(token.encode()).decode().split(".")
        good = hmac.new(_secret(db), f"{uid}.{exp}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good) or int(exp) < time.time():
            return None
        return db.get(User, int(uid))
    except (ValueError, UnicodeDecodeError):
        return None


def user_count(db: Session) -> int:
    return db.query(User).count()


_fails: dict[str, list[float]] = defaultdict(list)
WINDOW, MAX_FAILS = 300, 5


def locked_out(key: str) -> bool:
    now = time.time()
    _fails[key] = [t for t in _fails[key] if now - t < WINDOW]
    return len(_fails[key]) >= MAX_FAILS


def record_failure(key: str) -> None:
    _fails[key].append(time.time())


def clear_failures(key: str) -> None:
    _fails.pop(key, None)
