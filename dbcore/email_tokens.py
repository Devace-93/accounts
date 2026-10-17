"""Single-use email tokens behind the verification and magic links.

32 random bytes, stored as sha256 only. Issuing a token of a kind deletes the
user's previous unused tokens of that kind, so only the newest link works.
TTLs: ``MAGIC_TOKEN_TTL_MIN`` (15) and ``VERIFY_TOKEN_TTL_HOURS`` (24).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from .config import config
from .models import EmailToken, User

KINDS = ("verify", "magic")


class TokenConsumeError(Exception):
    """``code``: ``invalid_token`` | ``expired_token`` | ``used_token``."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def hash_token(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()


def ttl(kind: str) -> timedelta:
    if kind == "magic":
        return timedelta(minutes=config.magic_token_ttl_min)
    return timedelta(hours=config.verify_token_ttl_hours)


def issue(session, user: User, kind: str, *, return_to: str | None = None) -> str:
    """Create a token row and return the plaintext (goes into the mail link)."""
    if kind not in KINDS:
        raise ValueError(f"unknown token kind {kind!r}")
    session.execute(
        delete(EmailToken).where(EmailToken.user_id == user.id, EmailToken.kind == kind, EmailToken.used_at.is_(None))
    )
    plain = secrets.token_urlsafe(32)
    session.add(
        EmailToken(
            user_id=user.id,
            kind=kind,
            token_hash=hash_token(plain),
            return_to=(return_to or None),
            expires_at=datetime.now(timezone.utc) + ttl(kind),
        )
    )
    return plain


def consume(session, kind: str, plain: str) -> tuple[User, EmailToken]:
    """Mark the token used and return ``(user, row)``. Raises :class:`TokenConsumeError`."""
    if not plain or not isinstance(plain, str) or len(plain) > 200:
        raise TokenConsumeError("invalid_token")
    row = session.scalar(select(EmailToken).where(EmailToken.token_hash == hash_token(plain), EmailToken.kind == kind))
    if row is None:
        raise TokenConsumeError("invalid_token")
    if row.used_at is not None:
        raise TokenConsumeError("used_token")
    now = datetime.now(timezone.utc)
    if row.expires_at <= now:
        raise TokenConsumeError("expired_token")
    user = session.get(User, row.user_id)
    if user is None:
        raise TokenConsumeError("invalid_token")
    row.used_at = now
    return user, row
