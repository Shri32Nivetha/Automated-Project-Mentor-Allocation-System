import hashlib
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta

import bcrypt
from jose import JWTError, jwt

from .config import get_settings
from .database import utcnow
from .models import User

_s = get_settings()
PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,}$")


def validate_password_strength(pw: str) -> str:
    if not PASSWORD_RE.match(pw):
        raise ValueError("Password must be at least 8 characters and contain letters and numbers.")
    if len(pw.encode()) > 72:
        raise ValueError("Password must be at most 72 bytes long.")
    return pw


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_access_token(user: User) -> str:
    payload = {"sub": str(user.id), "tv": user.token_version,
               "exp": utcnow() + timedelta(minutes=_s.jwt_expire_minutes)}
    return jwt.encode(payload, _s.jwt_secret, algorithm=_s.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, _s.jwt_secret, algorithms=[_s.jwt_algorithm])
    except JWTError:
        return None


def new_reset_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_reset_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class RateLimiter:
    """Small in-process sliding-window limiter for login attempts (single-process deployments)."""

    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window:
            q.popleft()
        return len(q) < limit

    def hit(self, key: str):
        self.hits[key].append(time.monotonic())

    def reset(self, key: str | None = None):
        if key is None:
            self.hits.clear()
        else:
            self.hits.pop(key, None)


login_limiter = RateLimiter()
