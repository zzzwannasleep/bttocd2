"""Authentication helpers: password hashing + signed session cookies.

No native crypto deps — PBKDF2-HMAC-SHA256 from the stdlib for the password,
and itsdangerous for tamper-proof, expiring session cookies.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

log = logging.getLogger(__name__)

COOKIE_NAME = "bt2cd2_session"
_PBKDF2_ROUNDS = 200_000

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="bt2cd2-session")

# Failed-login throttling (per-process, best effort).
_failed: dict[str, list[float]] = {}
_LOCK_WINDOW = 300
_LOCK_THRESHOLD = 8


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)


def _resolve_password() -> str:
    """Return the configured admin password, generating one if absent."""
    if settings.web_password:
        return settings.web_password
    state = settings.data_dir / "web_password.txt"
    if state.exists():
        return state.read_text(encoding="utf-8").strip()
    generated = secrets.token_urlsafe(12)
    state.write_text(generated, encoding="utf-8")
    try:
        state.chmod(0o600)
    except OSError:
        pass
    log.warning(
        "No WEB_PASSWORD set. Generated a random admin password: %s "
        "(also saved to %s). Set WEB_PASSWORD to override.",
        generated,
        state,
    )
    return generated


_ADMIN_PASSWORD = _resolve_password()
_ADMIN_SALT = hashlib.sha256(settings.secret_key.encode()).digest()
_ADMIN_HASH = _hash_password(_ADMIN_PASSWORD, _ADMIN_SALT)


def _is_locked(ip: str) -> bool:
    now = time.time()
    attempts = [t for t in _failed.get(ip, []) if now - t < _LOCK_WINDOW]
    _failed[ip] = attempts
    return len(attempts) >= _LOCK_THRESHOLD


def _record_failure(ip: str) -> None:
    _failed.setdefault(ip, []).append(time.time())


def verify_login(username: str, password: str, ip: str = "?") -> bool:
    """Constant-time credential check with simple brute-force throttling."""
    if _is_locked(ip):
        log.warning("Login locked for %s (too many failures)", ip)
        return False
    candidate = _hash_password(password or "", _ADMIN_SALT)
    ok = hmac.compare_digest(username, settings.web_username) and hmac.compare_digest(candidate, _ADMIN_HASH)
    if not ok:
        _record_failure(ip)
    else:
        _failed.pop(ip, None)
    return ok


def issue_session(username: str) -> str:
    return _serializer.dumps({"u": username})


def validate_session(token: str | None) -> str | None:
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=settings.session_ttl_seconds)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("u")
