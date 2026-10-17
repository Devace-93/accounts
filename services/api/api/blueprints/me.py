"""Me blueprint: the signed-in user's profile (name, handle, password, avatar,
linked providers)."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, Response, g, jsonify, request
from sqlalchemy import select, update

from dbcore import avatars, handles
from dbcore.db import session_scope
from dbcore.mail_templates import pick_lang
from dbcore.models import Avatar, Identity, Session, User
from dbcore.outbox import enqueue_mail
from dbcore.posthog_client import capture

from ..auth_utils import hash_password, require_session, validate_password, verify_password
from ..errors import ApiError
from ..extensions import limiter, user_key
from ..serializers import json_body, serialize_identity, serialize_user

bp = Blueprint("me", __name__)

CSRF_HEADER_VALUE = "3m4"


def _load(session) -> User:
    user = session.get(User, g.user.id)
    if user is None:
        raise ApiError(401, "session_expired", "This session is no longer valid.")
    return user


@bp.get("")
@require_session
def me():
    with session_scope() as session:
        user = _load(session)
        identities = session.scalars(
            select(Identity).where(Identity.user_id == user.id).order_by(Identity.created_at)
        ).all()
        body = {
            "user": serialize_user(user),
            "has_password": user.password_hash is not None,
            "identities": [serialize_identity(i) for i in identities],
        }
    return jsonify(body)


@bp.patch("")
@require_session
def patch_me():
    from .auth import clean_name

    data = json_body()
    with session_scope() as session:
        user = _load(session)
        if "name" in data:
            user.name = clean_name(data.get("name"))
        if "handle" in data:
            try:
                handle = handles.validate(data.get("handle") or "")
            except handles.HandleError as err:
                raise ApiError(400, err.code, "Invalid or reserved handle.") from err
            if handle != user.handle and handles.is_taken(session, handle, exclude_user_id=user.id):
                raise ApiError(409, "handle_taken", "That handle is already taken.")
            user.handle = handle
        session.flush()
        body = {"user": serialize_user(user)}
    return jsonify(body)


@bp.put("/password")
@require_session
@limiter.limit("10 per hour", key_func=user_key)
def put_password():
    data = json_body()
    new_password = validate_password(data.get("new_password"))
    lang = pick_lang(data.get("lang"), request.headers.get("Accept-Language"))
    with session_scope() as session:
        user = _load(session)
        if user.password_hash is not None:
            current = data.get("current_password") if isinstance(data.get("current_password"), str) else ""
            if not verify_password(user.password_hash, current or ""):
                raise ApiError(401, "invalid_credentials", "Current password is incorrect.")
        user.password_hash = hash_password(new_password)
        session.execute(
            update(Session)
            .where(Session.user_id == user.id, Session.id != g.sid, Session.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        enqueue_mail(session, template="password_changed", to=user.email, lang=lang, user_id=user.id, name=user.name)
    return Response(status=204)


def _require_csrf_header() -> None:
    if request.headers.get("X-Requested-With") != CSRF_HEADER_VALUE:
        raise ApiError(403, "csrf_check_failed", "Send the header X-Requested-With: 3m4.")


@bp.put("/avatar")
@require_session
@limiter.limit("10 per hour", key_func=user_key)
def put_avatar():
    _require_csrf_header()
    upload = request.files.get("file")
    if upload is None:
        raise ApiError(400, "invalid_image", "Send the image as the multipart field 'file'.")
    data = upload.read(avatars.MAX_UPLOAD_BYTES + 1)
    try:
        webp = avatars.process_upload(data)
    except avatars.InvalidImage as err:
        status = 413 if err.code == "image_too_large" else 400
        raise ApiError(status, err.code, "Upload a PNG, JPEG, WebP or GIF of at most 2 MB.") from err
    with session_scope() as session:
        user = _load(session)
        row = session.get(Avatar, user.id)
        if row is None:
            session.add(Avatar(user_id=user.id, data=webp, content_type="image/webp"))
        else:
            row.data = webp
            row.content_type = "image/webp"
        user.avatar_version = (user.avatar_version or 0) + 1
        session.flush()
        body = {"user": serialize_user(user)}
        user_id = str(user.id)
    capture(user_id, "avatar_updated", {"action": "upload"})
    return jsonify(body)


@bp.delete("/avatar")
@require_session
def delete_avatar():
    with session_scope() as session:
        user = _load(session)
        row = session.get(Avatar, user.id)
        if row is not None:
            session.delete(row)
        user.avatar_version = (user.avatar_version or 0) + 1
        session.flush()
        body = {"user": serialize_user(user)}
        user_id = str(user.id)
    capture(user_id, "avatar_updated", {"action": "remove"})
    return jsonify(body)


@bp.delete("/identities/<provider>")
@require_session
def unlink_identity(provider: str):
    with session_scope() as session:
        user = _load(session)
        identities = session.scalars(select(Identity).where(Identity.user_id == user.id)).all()
        target = next((i for i in identities if i.provider == provider), None)
        if target is None:
            raise ApiError(404, "not_found", "That provider is not linked.")
        if user.password_hash is None and len(identities) == 1:
            raise ApiError(409, "last_login_method", "Set a password or link another provider before unlinking this one.")
        session.delete(target)
    return Response(status=204)
