"""Auth blueprint: signup, login, magic links, e-mail verification, providers.

Every success that starts a session answers ``{user}`` and sets the two
session cookies (see ``api.cookies``). Mails are queued in the outbox inside
the same transaction as the token they carry.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select

from dbcore import email_tokens, handles
from dbcore.db import session_scope
from dbcore.feature_flags import is_enabled
from dbcore.mail_templates import pick_lang
from dbcore.models import User
from dbcore.outbox import enqueue_mail
from dbcore.posthog_client import capture

from ..auth_utils import (
    attach,
    hash_password,
    issue_session,
    optional_user,
    require_session,
    validate_password,
    verify_password,
)
from ..errors import ApiError
from ..extensions import email_key, limiter, user_key
from ..features import require_feature
from ..returns import safe_return_to
from ..serializers import json_body, serialize_user
from .oauth import configured_providers

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")


def clean_email(value) -> str:
    email = (value or "").strip().lower() if isinstance(value, str) else ""
    if not email or len(email) > 255 or not EMAIL_RE.match(email):
        raise ApiError(400, "invalid_email", "A valid e-mail address is required.")
    return email


def request_lang(data: dict | None = None) -> str:
    return pick_lang((data or {}).get("lang"), request.headers.get("Accept-Language"))


def clean_name(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(400, "invalid_name", "Name must be a string.")
    name = " ".join(value.split())
    if not name:
        return None
    if len(name) > 80:
        raise ApiError(400, "invalid_name", "Name must be at most 80 characters.")
    return name


def resolve_handle(session, requested, *, email: str) -> str:
    """The handle to store: the requested one (validated, must be free) or a
    unique one derived from the e-mail."""
    if requested:
        try:
            handle = handles.validate(requested)
        except handles.HandleError as err:
            raise ApiError(400, err.code, _handle_message(err.code)) from err
        if handles.is_taken(session, handle):
            raise ApiError(409, "handle_taken", "That handle is already taken.")
        return handle
    return handles.unique_from(session, handles.from_email(email))


def _handle_message(code: str) -> str:
    if code == "reserved_handle":
        return "That handle is reserved."
    return "Handles are 3-32 lowercase letters, digits or single hyphens, and cannot start or end with a hyphen."


def _session_response(session, user, status: int = 200, extra: dict | None = None):
    access, refresh, _claims = issue_session(session, user)
    body = {"user": serialize_user(user)}
    if extra:
        body.update(extra)
    resp = jsonify(body)
    resp.status_code = status
    return attach(resp, access, refresh)


def queue_verification(session, user: User, lang: str, return_to: str | None = None) -> None:
    token = email_tokens.issue(session, user, "verify", return_to=return_to)
    enqueue_mail(session, template="verify", to=user.email, lang=lang, user_id=user.id, name=user.name,
                 token=token, return_to=return_to)


# --------------------------------------------------------------------------- #
@bp.post("/signup")
@limiter.limit("5 per minute")
@require_feature("signups", code="signups_disabled")
def signup():
    data = json_body()
    email = clean_email(data.get("email"))
    password = validate_password(data.get("password"))
    name = clean_name(data.get("name"))
    lang = request_lang(data)
    return_to = data.get("return_to") if isinstance(data.get("return_to"), str) else None

    with session_scope() as session:
        if session.scalar(select(User.id).where(User.email == email)) is not None:
            raise ApiError(409, "email_taken", "An account with that e-mail already exists.")
        handle = resolve_handle(session, data.get("handle"), email=email)
        user = User(email=email, password_hash=hash_password(password), handle=handle, name=name)
        session.add(user)
        session.flush()
        queue_verification(session, user, lang, return_to)
        resp = _session_response(session, user, status=201)
        user_id = str(user.id)
    capture(user_id, "signup", {"method": "password"})
    return resp


@bp.post("/login")
@limiter.limit("10 per minute")
def login():
    data = json_body()
    email = (data.get("email") or "").strip().lower() if isinstance(data.get("email"), str) else ""
    password = data.get("password") if isinstance(data.get("password"), str) else ""
    with session_scope() as session:
        user = session.scalar(select(User).where(User.email == email)) if email else None
        # verify_password checks a dummy hash when the user is unknown or has
        # no password, so every failure costs the same time.
        ok = verify_password(user.password_hash if user else None, password or "")
        if not ok or user is None:
            raise ApiError(401, "invalid_credentials", "E-mail or password is incorrect.")
        resp = _session_response(session, user)
        user_id = str(user.id)
    capture(user_id, "login", {"method": "password"})
    return resp


# --------------------------------------------------------------------------- #
# Magic links
# --------------------------------------------------------------------------- #
@bp.post("/magic")
@limiter.limit("3 per minute")
@limiter.limit("5 per hour", key_func=email_key)
@require_feature("magic-link")
def magic():
    data = json_body()
    email = clean_email(data.get("email"))
    lang = request_lang(data)
    raw_return = data.get("return_to") if isinstance(data.get("return_to"), str) else None
    return_to = safe_return_to(raw_return) if raw_return else None
    with session_scope() as session:
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            enqueue_mail(session, template="magic_no_account", to=email, lang=lang)
        else:
            token = email_tokens.issue(session, user, "magic", return_to=return_to)
            enqueue_mail(session, template="magic", to=user.email, lang=lang, user_id=user.id, name=user.name,
                         token=token, return_to=return_to)
            capture(str(user.id), "magic_link_requested", {})
    return jsonify({}), 202


@bp.post("/magic/consume")
@limiter.limit("20 per minute")
def magic_consume():
    data = json_body()
    with session_scope() as session:
        try:
            user, row = email_tokens.consume(session, "magic", data.get("token"))
        except email_tokens.TokenConsumeError as err:
            raise ApiError(400, err.code, _token_message(err.code)) from err
        first_verification = user.email_verified_at is None
        if first_verification:
            user.email_verified_at = datetime.now(timezone.utc)
        resp = _session_response(session, user, extra={"return_to": safe_return_to(row.return_to)})
        user_id = str(user.id)
    capture(user_id, "login", {"method": "magic"})
    if first_verification:
        capture(user_id, "email_verified", {"via": "magic"})
    return resp


def _token_message(code: str) -> str:
    return {
        "expired_token": "This link has expired. Request a new one.",
        "used_token": "This link was already used. Request a new one.",
    }.get(code, "This link is not valid.")


# --------------------------------------------------------------------------- #
# E-mail verification
# --------------------------------------------------------------------------- #
@bp.post("/verify/consume")
@limiter.limit("20 per minute")
def verify_consume():
    data = json_body()
    # The caller usually clicks the mailed link in the browser that signed up,
    # so it already holds a session whose JWT still says email_verified=false.
    # Re-issue that session so the claim flips now instead of at the next
    # refresh (up to SESSION_TTL_MIN later, during which every relying app
    # would keep answering 403 email_unverified).
    current = optional_user()
    tokens = None
    with session_scope() as session:
        try:
            user, row = email_tokens.consume(session, "verify", data.get("token"))
        except email_tokens.TokenConsumeError as err:
            raise ApiError(400, err.code, _token_message(err.code)) from err
        if user.email_verified_at is None:
            user.email_verified_at = datetime.now(timezone.utc)
            session.flush()
        if current is not None and current.id == user.id:
            access, refresh_plain, _claims = issue_session(session, user)
            tokens = (access, refresh_plain)
        body = {"user": serialize_user(user), "return_to": safe_return_to(row.return_to)}
        user_id = str(user.id)
    capture(user_id, "email_verified", {"via": "link"})
    resp = jsonify(body)
    return attach(resp, *tokens) if tokens else resp


@bp.post("/verify/resend")
@require_session
@limiter.limit("3 per hour", key_func=user_key)
def verify_resend():
    data = json_body()
    lang = request_lang(data)
    with session_scope() as session:
        user = session.get(User, g.user.id)
        if user.email_verified_at is not None:
            raise ApiError(409, "already_verified", "This e-mail is already verified.")
        queue_verification(session, user, lang)
    return jsonify({}), 202


# --------------------------------------------------------------------------- #
@bp.get("/providers")
def providers():
    enabled = configured_providers() if is_enabled("oauth") else []
    return jsonify({"providers": enabled})
