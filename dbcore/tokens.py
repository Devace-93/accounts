"""The session JWT (``3m4_session`` cookie / bearer): sign and verify.

Claims are exactly the ones in CONTRACT.md → "Session model". Verification
here is what the accounts API itself does; relying apps use the same rules
through the public JWKS (``packages/relying-party/python/m4session.py``).
"""
from __future__ import annotations

import time
import uuid

import jwt

from .config import config
from .keys import keyring


class TokenError(Exception):
    """``code`` is one of ``session_expired`` / ``invalid_session``."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def avatar_url(user_id, version: int) -> str:
    return f"{config.accounts_url}/avatars/{user_id}?v={int(version or 0)}"


def session_claims(user, sid, *, now: int | None = None) -> dict:
    now = int(now if now is not None else time.time())
    return {
        "iss": config.accounts_url,
        "aud": config.jwt_audience,
        "sub": str(user.id),
        "sid": str(sid),
        "email": user.email,
        "email_verified": user.email_verified_at is not None,
        "handle": user.handle,
        "name": user.name,
        "avatar_url": avatar_url(user.id, user.avatar_version),
        "iat": now,
        "exp": now + config.session_ttl_min * 60,
    }


def sign_session(user, sid) -> tuple[str, dict]:
    """Returns ``(token, claims)``."""
    ring = keyring()
    claims = session_claims(user, sid)
    token = jwt.encode(claims, ring.private_key, algorithm="EdDSA", headers={"kid": ring.kid})
    return token, claims


def verify_session(token: str, *, verify_exp: bool = True) -> dict:
    """Decode + verify a session JWT with the local key ring.

    Raises :class:`TokenError` with ``session_expired`` or ``invalid_session``.
    """
    ring = keyring()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as err:
        raise TokenError("invalid_session") from err
    public = ring.public_key_by_kid(header.get("kid"))
    if public is None:
        raise TokenError("invalid_session")
    try:
        claims = jwt.decode(
            token,
            public,
            algorithms=["EdDSA"],
            audience=config.jwt_audience,
            issuer=config.accounts_url,
            options={"verify_exp": verify_exp, "require": ["sub", "sid", "exp", "iat"]},
        )
    except jwt.ExpiredSignatureError as err:
        raise TokenError("session_expired") from err
    except jwt.PyJWTError as err:
        raise TokenError("invalid_session") from err
    try:
        uuid.UUID(claims["sub"])
        uuid.UUID(claims["sid"])
    except (ValueError, KeyError, TypeError) as err:
        raise TokenError("invalid_session") from err
    return claims
