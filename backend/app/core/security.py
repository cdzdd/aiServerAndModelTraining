import hashlib
import hmac
import secrets
from functools import lru_cache
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

password_hasher = PasswordHasher()
SESSION_COOKIE = "qa_session"
PRELOGIN_COOKIE = "qa_prelogin"
SESSION_SECONDS = 86400
PRELOGIN_SECONDS = 600


class AuthError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sign(secret: str, purpose: str, value: str) -> str:
    return hmac.new(secret.encode(), f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


def csrf_token(secret: str, cookie: str) -> str:
    return sign(secret, "csrf", cookie)


def new_prelogin(secret: str, now: float) -> str:
    value = f"{int(now) + PRELOGIN_SECONDS}.{secrets.token_urlsafe(32)}"
    return f"{value}.{sign(secret, 'prelogin', value)}"


def valid_prelogin(secret: str, cookie: str, now: float) -> bool:
    try:
        value, signature = cookie.rsplit(".", 1)
        expires, nonce = value.split(".", 1)
        return (
            len(nonce) == 43
            and now < int(expires) <= now + PRELOGIN_SECONDS
            and hmac.compare_digest(signature, sign(secret, "prelogin", value))
        )
    except (ValueError, TypeError):
        return False


def origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return None
        if parsed.username or parsed.password:
            return None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return f"{parsed.scheme}://{parsed.hostname.lower()}:{port}"
    except ValueError:
        return None


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    return password_hasher.hash(secrets.token_urlsafe(32))


def verify_password(hashed: str, password: str) -> bool:
    try:
        return password_hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False
