"""Handles: the public username (`/{handle}/…` in smart-docs, the leaderboard
name in bubbles). Rules from CONTRACT.md → "Objects".
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from sqlalchemy import select

from ._shared import load_shared

HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$")  # 3–32 chars
MIN_LEN, MAX_LEN = 3, 32

_non_word = re.compile(r"[^a-z0-9]+")


class HandleError(ValueError):
    """``code``: ``invalid_handle`` | ``reserved_handle`` | ``handle_taken``."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@lru_cache(maxsize=1)
def reserved() -> frozenset[str]:
    return frozenset(h.lower() for h in load_shared("reserved_handles.json")["handles"])


def is_valid(handle: str) -> bool:
    return isinstance(handle, str) and bool(HANDLE_RE.match(handle))


def normalize(raw: str) -> str:
    return (raw or "").strip().lower()


def slugify(value: str) -> str:
    """Best-effort handle from free text (email local part, provider login, name)."""
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    value = _non_word.sub("-", value).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    value = value[:MAX_LEN].strip("-")
    if len(value) < MIN_LEN:
        value = (value + "-user")[:MAX_LEN].strip("-") if value else "user"
    return value


def from_email(email: str) -> str:
    return slugify(email.split("@", 1)[0])


def validate(handle: str) -> str:
    """Normalise and check syntax + reserved list. Returns the clean handle."""
    clean = normalize(handle)
    if not is_valid(clean):
        raise HandleError("invalid_handle")
    if clean in reserved():
        raise HandleError("reserved_handle")
    return clean


def is_taken(session, handle: str, *, exclude_user_id=None) -> bool:
    from .models import User

    stmt = select(User.id).where(User.handle == handle)
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return session.scalar(stmt) is not None


def unique_from(session, seed: str) -> str:
    """``seed``, or ``seed-2``, ``seed-3``… — the first free, non-reserved handle."""
    base = slugify(seed)
    candidate = base
    n = 1
    while candidate in reserved() or is_taken(session, candidate):
        n += 1
        suffix = f"-{n}"
        candidate = base[: MAX_LEN - len(suffix)].rstrip("-") + suffix
    return candidate
