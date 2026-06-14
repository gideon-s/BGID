"""Password hashing (Argon2) + JWT issuing/verification.

Mirrors the dreamcrawler auth primitives, adapted for BGID's plain-module
config (no Settings object) and integer user ids. Tokens are HS256-signed.
Access tokens are short-lived; refresh tokens are long-lived and carry a
`jti` so they can be revoked (see models.RevokedToken).
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

import config

_logger = logging.getLogger(__name__)

# Resolve the signing secret once at import. A blank JWT_SECRET is allowed for
# local dev/tests — we mint an ephemeral per-process secret so the app still
# runs, but tokens won't survive a restart and every process has its own key.
_SECRET = config.JWT_SECRET
if not _SECRET:
    _SECRET = secrets.token_hex(32)
    _logger.warning(
        "JWT_SECRET is not set — using an ephemeral per-process secret. "
        "Tokens will be invalidated on restart. Set JWT_SECRET in .env for production."
    )

ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed_password: str) -> bool:
    return ph.check_needs_rehash(hashed_password)


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": str(subject), "exp": expire, "type": "access"}
    return jwt.encode(payload, _SECRET, algorithm=config.JWT_ALGORITHM)


def create_refresh_token(subject: str) -> tuple[str, str]:
    """Returns (token, jti). Store the jti to allow revocation on logout."""
    expire = datetime.now(timezone.utc) + timedelta(days=config.REFRESH_TOKEN_EXPIRE_DAYS)
    jti = secrets.token_hex(16)
    payload = {"sub": str(subject), "exp": expire, "type": "refresh", "jti": jti}
    token = jwt.encode(payload, _SECRET, algorithm=config.JWT_ALGORITHM)
    return token, jti


def decode_token(token: str) -> dict:
    """Decode + verify a token. Raises jose.JWTError on any failure
    (bad signature, expired, malformed)."""
    return jwt.decode(token, _SECRET, algorithms=[config.JWT_ALGORITHM])
