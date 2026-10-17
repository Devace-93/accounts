"""Passwords, session issuance and the ``@require_session`` decorator.

Inside the accounts API a request is authenticated by the ``3m4_session``
cookie (or the same JWT as a bearer token). On top of the local JWT
verification that relying apps also do, this service checks that the
session row behind ``sid`` is still alive, so a logout is immediate here.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import Response, g, request

from dbcore.config import config
from dbcore.db import SessionLocal
from dbcore.email_tokens import hash_token
from dbcore.models import Session, User
from dbcore.privacy import ip_hash
from dbcore.tokens import TokenError, sign_session, verify_session

from .cookies import SESSION_COOKIE, set_session_cookies
from .errors import ApiError
from .extensions import client_ip

_ph = PasswordHasher()
# Verified against when the e-mail is unknown or the user has no password, so
# a login attempt costs the same either way (no account enumeration).
_DUMMY_HASH = _ph.hash("not-a-real-password")

MIN_PASSWORD, MAX_PASSWORD = 8, 256


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _ph.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except Exception:
        return False


def validate_password(password) -> str:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise ApiError(400, "weak_password", f"Password must be at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise ApiError(400, "weak_password", f"Password must be at most {MAX_PASSWORD} characters.")
    return password


def now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Issuing sessions
# --------------------------------------------------------------------------- #
def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def create_session_row(session, user: User) -> tuple[Session, str]:
    """Insert the refresh-token row for ``user``. Returns ``(row, plaintext refresh)``."""
    plain = new_refresh_token()
    row = Session(
        user_id=user.id,
        refresh_hash=hash_token(plain),
        user_agent=(request.user_agent.string or "")[:300] or None,
        ip_hash=ip_hash(client_ip()),
        expires_at=now() + timedelta(days=config.refresh_ttl_days),
    )
    session.add(row)
    session.flush()
    return row, plain


def issue_session(session, user: User) -> tuple[str, str, dict]:
    """Create the session row and sign the JWT. Returns
    ``(access_token, refresh_token, claims)``; set the cookies on the
    response with :func:`attach`."""
    row, refresh_plain = create_session_row(session, user)
    access, claims = sign_session(user, row.id)
    return access, refresh_plain, claims


def attach(resp: Response, access: str, refresh: str) -> Response:
    set_session_cookies(resp, access, refresh)
    return resp


# --------------------------------------------------------------------------- #
# Reading sessions
# --------------------------------------------------------------------------- #
def current_token() -> str | None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        return token
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip() or None
    return None


def load_session(claims: dict) -> tuple[User, Session]:
    """The live ``(user, session row)`` behind verified claims, or 401."""
    with SessionLocal() as db:
        row = db.get(Session, uuid.UUID(claims["sid"]))
        user = db.get(User, uuid.UUID(claims["sub"]))
    if row is None or user is None or row.revoked_at is not None or row.expires_at <= now():
        raise ApiError(401, "session_expired", "This session is no longer valid.")
    return user, row


def authenticate() -> None:
    """Populate ``g.user`` / ``g.sid`` / ``g.claims`` or raise 401."""
    token = current_token()
    if not token:
        raise ApiError(401, "no_session", "Not signed in.")
    try:
        claims = verify_session(token)
    except TokenError as err:
        message = "Session expired." if err.code == "session_expired" else "Invalid session."
        raise ApiError(401, err.code, message) from err
    user, row = load_session(claims)
    g.user = user
    g.sid = row.id
    g.claims = claims


def require_session(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        authenticate()
        return view(*args, **kwargs)

    return wrapper


def optional_user() -> User | None:
    """``g.user`` when a valid session is presented, else None (never raises)."""
    try:
        authenticate()
    except ApiError:
        return None
    return g.user
