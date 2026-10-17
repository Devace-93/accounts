"""Session blueprint: the endpoints the widget and the apps call.

``GET /`` is the cheap "who am I" (access cookie / bearer only). ``refresh``
rotates the refresh token and re-signs the JWT. ``logout`` revokes and
clears. ``list`` / ``DELETE /<id>`` back the sessions panel on the profile.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, Response, g, jsonify, request
from sqlalchemy import select, update

from dbcore.config import config
from dbcore.db import session_scope
from dbcore.email_tokens import hash_token
from dbcore.models import Session, User
from dbcore.posthog_client import capture
from dbcore.tokens import TokenError, sign_session, verify_session

from ..auth_utils import attach, current_token, new_refresh_token, require_session
from ..cookies import REFRESH_COOKIE, clear_session_cookies
from ..errors import ApiError
from ..extensions import limiter
from ..serializers import iso, json_body, serialize_session_row, serialize_user

bp = Blueprint("session", __name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cleared_error(status: int, code: str, message: str) -> Response:
    resp = jsonify({"error": {"code": code, "message": message}})
    resp.status_code = status
    clear_session_cookies(resp)
    return resp


@bp.get("")
@require_session
def current():
    exp = g.claims.get("exp")
    with session_scope() as session:
        row = session.get(Session, g.sid)
        if row is not None and (row.last_seen_at is None or _now() - row.last_seen_at > timedelta(seconds=60)):
            row.last_seen_at = _now()
    return jsonify({
        "user": serialize_user(g.user),
        "session": {"id": str(g.sid), "expires_at": iso(datetime.fromtimestamp(exp, tz=timezone.utc)) if exp else None},
    })


@bp.post("/refresh")
@limiter.limit("60 per minute")
def refresh():
    plain = request.cookies.get(REFRESH_COOKIE)
    if not plain:
        return _cleared_error(401, "invalid_refresh", "No refresh token.")
    with session_scope() as session:
        row = session.scalar(select(Session).where(Session.refresh_hash == hash_token(plain)))
        if row is None or row.revoked_at is not None or row.expires_at <= _now():
            return _cleared_error(401, "invalid_refresh", "Refresh token is invalid or expired.")
        user = session.get(User, row.user_id)
        if user is None:
            return _cleared_error(401, "invalid_refresh", "Refresh token is invalid or expired.")
        new_plain = new_refresh_token()
        row.refresh_hash = hash_token(new_plain)
        row.expires_at = _now() + timedelta(days=config.refresh_ttl_days)
        row.last_seen_at = _now()
        row.user_agent = (request.user_agent.string or "")[:300] or row.user_agent
        access, _claims = sign_session(user, row.id)
        body = {"user": serialize_user(user)}
    return attach(jsonify(body), access, new_plain)


@bp.post("/logout")
def logout():
    data = json_body()
    revoke_all = bool(data.get("all"))
    user_id = sid = None
    token = current_token()
    if token:
        try:
            claims = verify_session(token, verify_exp=False)
            user_id, sid = uuid.UUID(claims["sub"]), uuid.UUID(claims["sid"])
        except TokenError:
            pass
    refresh_plain = request.cookies.get(REFRESH_COOKIE)
    with session_scope() as session:
        if sid is None and refresh_plain:
            row = session.scalar(select(Session).where(Session.refresh_hash == hash_token(refresh_plain)))
            if row is not None:
                user_id, sid = row.user_id, row.id
        if revoke_all and user_id is not None:
            session.execute(update(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None)).values(revoked_at=_now()))
        elif sid is not None:
            session.execute(update(Session).where(Session.id == sid, Session.revoked_at.is_(None)).values(revoked_at=_now()))
    if user_id is not None:
        capture(str(user_id), "logout", {"all": revoke_all})
    resp = Response(status=204)
    clear_session_cookies(resp)
    return resp


@bp.get("/list")
@require_session
def list_sessions():
    with session_scope() as session:
        rows = session.scalars(
            select(Session)
            .where(Session.user_id == g.user.id, Session.revoked_at.is_(None), Session.expires_at > _now())
            .order_by(Session.last_seen_at.desc())
        ).all()
        items = [serialize_session_row(r, g.sid) for r in rows]
    return jsonify({"items": items})


@bp.delete("/<session_id>")
@require_session
def revoke(session_id: str):
    try:
        target = uuid.UUID(session_id)
    except ValueError:
        raise ApiError(404, "not_found", "Session not found.")
    with session_scope() as session:
        row = session.get(Session, target)
        if row is None or row.user_id != g.user.id:
            raise ApiError(404, "not_found", "Session not found.")
        if row.revoked_at is None:
            row.revoked_at = _now()
    resp = Response(status=204)
    if target == g.sid:
        clear_session_cookies(resp)
    return resp
