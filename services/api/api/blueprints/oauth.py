"""OAuth sign-in / sign-up / linking with Google, GitHub, Microsoft and
Discord (Authlib).

Flow: ``GET /start`` stores ``return_to`` / ``link`` intent next to Authlib's
state, nonce and PKCE verifier in the signed ``3m4_oauth`` cookie (Flask's
session cookie, scoped to these routes, 10 min) and redirects to the
provider. ``GET /callback`` exchanges the code, normalises the provider
profile into :class:`ProviderProfile` and runs :func:`complete`, which holds
every rule from CONTRACT.md:

* identity already known → log that user in;
* ``link=1`` → attach the identity to the signed-in user (unless it already
  belongs to someone else: ``identity_taken``);
* unknown identity + known e-mail → link only when the provider says the
  e-mail is verified, else ``oauth_email_unverified``;
* unknown identity + unknown e-mail → create the user (needs ``signups``),
  verified when the provider says so, avatar copied when available.

Trust notes: Google and Discord expose ``email_verified`` / ``verified``.
GitHub lists its e-mails with a ``verified`` flag and we pick the primary
verified one. Microsoft's OIDC userinfo ``email`` claim is treated as
verified (Microsoft verifies account e-mails; ``preferred_username`` is NOT
used because it can be an unverified alias).

Failures never raise to the browser: they redirect to
``/login?error=<code>&provider=<name>`` on the accounts site.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from flask import Blueprint, redirect, request, session as flask_session, url_for
from sqlalchemy import select

from dbcore import avatars, handles
from dbcore.config import config
from dbcore.db import session_scope
from dbcore.feature_flags import is_enabled
from dbcore.models import Avatar, Identity, User
from dbcore.posthog_client import capture

from ..auth_utils import attach, issue_session, optional_user
from ..errors import ApiError
from ..extensions import limiter, oauth
from ..returns import safe_return_to

log = logging.getLogger("accounts.oauth")

bp = Blueprint("oauth", __name__)

PROVIDERS = ("google", "github", "microsoft", "discord")
CTX_KEY = "oauth_ctx"


class OAuthFailure(Exception):
    """``code`` ends up in ``/login?error=<code>``."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class ProviderProfile:
    provider: str
    provider_user_id: str
    email: str | None
    email_verified: bool
    name: str | None = None
    login: str | None = None
    picture: str | None = None
    raw: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def configured_providers() -> list[str]:
    return [p for p in PROVIDERS if config.oauth_credentials(p)]


def register_providers(registry) -> None:
    """Register every provider that has credentials on the Authlib registry."""
    creds = config.oauth_credentials("google")
    if creds:
        registry.register(
            name="google",
            client_id=creds[0],
            client_secret=creds[1],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
        )
    creds = config.oauth_credentials("github")
    if creds:
        registry.register(
            name="github",
            client_id=creds[0],
            client_secret=creds[1],
            authorize_url="https://github.com/login/oauth/authorize",
            access_token_url="https://github.com/login/oauth/access_token",
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "read:user user:email"},
        )
    creds = config.oauth_credentials("microsoft")
    if creds:
        tenant = config.oauth_microsoft_tenant
        registry.register(
            name="microsoft",
            client_id=creds[0],
            client_secret=creds[1],
            authorize_url=f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
            access_token_url=f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            api_base_url="https://graph.microsoft.com/",
            client_kwargs={"scope": "openid email profile User.Read", "code_challenge_method": "S256"},
        )
    creds = config.oauth_credentials("discord")
    if creds:
        registry.register(
            name="discord",
            client_id=creds[0],
            client_secret=creds[1],
            authorize_url="https://discord.com/oauth2/authorize",
            access_token_url="https://discord.com/api/oauth2/token",
            api_base_url="https://discord.com/api/",
            client_kwargs={"scope": "identify email", "code_challenge_method": "S256"},
        )


def _client(provider: str):
    if provider not in PROVIDERS:
        raise ApiError(404, "unknown_provider", "Unknown provider.")
    if provider not in configured_providers():
        raise ApiError(404, "provider_not_configured", f"{provider} sign-in is not configured.")
    if not is_enabled("oauth"):
        raise ApiError(403, "feature_disabled", "'oauth' is not available.")
    return oauth.create_client(provider)


# --------------------------------------------------------------------------- #
# Provider profile normalisation
# --------------------------------------------------------------------------- #
def fetch_profile(provider: str, client, token: dict) -> ProviderProfile:
    if provider == "google":
        info = token.get("userinfo") or client.userinfo(token=token)
        picture = info.get("picture")
        if picture and "=s96-c" in picture:
            picture = picture.replace("=s96-c", "=s256-c")
        return ProviderProfile(
            provider, str(info["sub"]), info.get("email"), bool(info.get("email_verified")),
            name=info.get("name"), login=None, picture=picture, raw=dict(info),
        )
    if provider == "github":
        user = client.get("user", token=token).json()
        email, verified = user.get("email"), False
        try:
            emails = client.get("user/emails", token=token).json()
            if isinstance(emails, list):
                primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
                any_verified = next((e for e in emails if e.get("verified")), None)
                chosen = primary or any_verified
                if chosen:
                    email, verified = chosen["email"], True
        except Exception:  # pragma: no cover - network / shape surprises
            pass
        picture = user.get("avatar_url")
        if picture:
            picture = f"{picture}{'&' if '?' in picture else '?'}s=256"
        return ProviderProfile(
            provider, str(user["id"]), email, verified,
            name=user.get("name"), login=user.get("login"), picture=picture,
            raw={k: user.get(k) for k in ("id", "login", "name", "html_url")},
        )
    if provider == "microsoft":
        info = client.get("oidc/userinfo", token=token).json()
        email = info.get("email")
        picture = None  # fetched lazily by picture_bytes (binary endpoint)
        return ProviderProfile(
            provider, str(info["sub"]), email, bool(email),
            name=info.get("name"), login=None, picture=picture,
            raw={k: info.get(k) for k in ("sub", "name", "email")},
        )
    if provider == "discord":
        me = client.get("users/@me", token=token).json()
        picture = None
        if me.get("avatar"):
            picture = f"https://cdn.discordapp.com/avatars/{me['id']}/{me['avatar']}.png?size=256"
        return ProviderProfile(
            provider, str(me["id"]), me.get("email"), bool(me.get("verified")),
            name=me.get("global_name") or me.get("username"), login=me.get("username"), picture=picture,
            raw={k: me.get(k) for k in ("id", "username", "global_name")},
        )
    raise OAuthFailure("unknown_provider")


def picture_bytes(provider: str, client, token: dict, profile: ProviderProfile) -> bytes | None:
    """Download the provider picture, already normalised to our WebP; None on any problem."""
    try:
        if provider == "microsoft":
            resp = client.get("v1.0/me/photo/$value", token=token)
            data = resp.content if resp.status_code == 200 else None
        elif profile.picture:
            data = requests.get(profile.picture, timeout=5).content
        else:
            return None
        return avatars.process_upload(data) if data else None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Core rules (pure of HTTP, so tests can drive them with a fake profile)
# --------------------------------------------------------------------------- #
def derive_handle(session, profile: ProviderProfile) -> str:
    seed = profile.login or (profile.email.split("@", 1)[0] if profile.email else None) or profile.name or "user"
    return handles.unique_from(session, seed)


def complete(profile: ProviderProfile, *, link_user_id=None, avatar_webp: bytes | None = None) -> tuple[User, str]:
    """Apply the CONTRACT rules. Returns ``(user, event)`` where ``event`` is
    ``login`` / ``signup`` / ``linked``; raises :class:`OAuthFailure`."""
    with session_scope() as session:
        identity = session.scalar(
            select(Identity).where(Identity.provider == profile.provider, Identity.provider_user_id == profile.provider_user_id)
        )
        if link_user_id is not None:
            user = session.get(User, link_user_id)
            if user is None:
                raise OAuthFailure("no_session")
            if identity is not None and identity.user_id != user.id:
                raise OAuthFailure("identity_taken")
            if identity is None:
                session.add(Identity(user_id=user.id, provider=profile.provider, provider_user_id=profile.provider_user_id,
                                     provider_email=profile.email, profile=profile.raw))
                if profile.email_verified and user.email_verified_at is None and profile.email == user.email:
                    user.email_verified_at = datetime.now(timezone.utc)
            session.flush()
            session.expunge(user)
            return user, "linked"

        if identity is not None:
            user = session.get(User, identity.user_id)
            if user is None:
                raise OAuthFailure("oauth_failed")
            session.expunge(user)
            return user, "login"

        if not profile.email:
            raise OAuthFailure("oauth_no_email")
        email = profile.email.strip().lower()
        user = session.scalar(select(User).where(User.email == email))
        if user is not None:
            if not profile.email_verified:
                raise OAuthFailure("oauth_email_unverified")
            session.add(Identity(user_id=user.id, provider=profile.provider, provider_user_id=profile.provider_user_id,
                                 provider_email=email, profile=profile.raw))
            if user.email_verified_at is None:
                user.email_verified_at = datetime.now(timezone.utc)
            session.flush()
            session.expunge(user)
            return user, "login"

        if not is_enabled("signups"):
            raise OAuthFailure("signups_disabled")
        user = User(
            email=email,
            password_hash=None,
            handle=derive_handle(session, profile),
            name=(profile.name or "").strip()[:80] or None,
            email_verified_at=datetime.now(timezone.utc) if profile.email_verified else None,
        )
        session.add(user)
        session.flush()
        session.add(Identity(user_id=user.id, provider=profile.provider, provider_user_id=profile.provider_user_id,
                             provider_email=email, profile=profile.raw))
        if avatar_webp:
            session.add(Avatar(user_id=user.id, data=avatar_webp, content_type="image/webp"))
            user.avatar_version = 1
        session.flush()
        session.expunge(user)
        return user, "signup"


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
def _login_redirect(code: str, provider: str):
    return redirect(f"{config.accounts_url}/login?{urlencode({'error': code, 'provider': provider})}")


@bp.get("/<provider>/start")
@limiter.limit("20 per minute")
def start(provider: str):
    client = _client(provider)
    link = request.args.get("link") == "1"
    ctx = {"return_to": safe_return_to(request.args.get("return_to")), "link": link, "link_user_id": None}
    if link:
        user = optional_user()
        if user is None:
            raise ApiError(401, "no_session", "Sign in before linking a provider.")
        ctx["link_user_id"] = str(user.id)
    flask_session.permanent = True
    flask_session[CTX_KEY] = ctx
    redirect_uri = f"{config.accounts_url}{url_for('oauth.callback', provider=provider)}"
    return client.authorize_redirect(redirect_uri)


@bp.get("/<provider>/callback")
@limiter.limit("20 per minute")
def callback(provider: str):
    ctx = flask_session.pop(CTX_KEY, None) or {}
    try:
        client = _client(provider)
    except ApiError as err:
        return _login_redirect(err.code, provider)
    if request.args.get("error"):
        return _login_redirect("oauth_denied", provider)
    try:
        token = client.authorize_access_token()
        profile = fetch_profile(provider, client, token)
    except Exception as err:  # Authlib raises many flavours; none are the user's fault to debug
        log.warning("oauth %s callback failed: %s", provider, type(err).__name__)
        flask_session.clear()
        return _login_redirect("oauth_failed", provider)
    link_user_id = uuid.UUID(ctx["link_user_id"]) if ctx.get("link") and ctx.get("link_user_id") else None
    avatar_webp = None
    if link_user_id is None:
        with session_scope() as db:
            known = db.scalar(select(Identity.id).where(Identity.provider == provider, Identity.provider_user_id == profile.provider_user_id))
            known_email = profile.email and db.scalar(select(User.id).where(User.email == profile.email.lower()))
        if not known and not known_email:
            avatar_webp = picture_bytes(provider, client, token, profile)
    try:
        user, event = complete(profile, link_user_id=link_user_id, avatar_webp=avatar_webp)
    except OAuthFailure as err:
        flask_session.clear()
        if err.code == "identity_taken":
            return redirect(f"{config.accounts_url}/profile?{urlencode({'error': err.code, 'provider': provider})}")
        return _login_redirect(err.code, provider)
    flask_session.clear()
    return_to = safe_return_to(ctx.get("return_to"))
    if event == "linked":
        capture(str(user.id), "identity_linked", {"provider": provider})
        return redirect(return_to)
    with session_scope() as db:
        fresh = db.get(User, user.id)
        access, refresh, _ = issue_session(db, fresh)
    capture(str(user.id), event, {"method": provider})
    if event == "signup" and user.email_verified_at is not None:
        capture(str(user.id), "email_verified", {"via": provider})
    return attach(redirect(return_to), access, refresh)
