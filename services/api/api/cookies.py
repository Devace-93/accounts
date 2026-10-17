"""The two session cookies, exactly as CONTRACT.md → "Session model" says.

``3m4_session``  JWT, Path=/, Domain=COOKIE_DOMAIN (``.3m4.net`` in prod)
``3m4_refresh``  opaque, Path=/api/session, host-only (accounts itself)
Both HttpOnly, SameSite=Lax, Secure when COOKIE_SECURE.
"""
from __future__ import annotations

from flask import Response

from dbcore.config import config

SESSION_COOKIE = "3m4_session"
REFRESH_COOKIE = "3m4_refresh"
REFRESH_PATH = "/api/session"


def _domain() -> str | None:
    return config.cookie_domain or None


def set_session_cookies(resp: Response, access_token: str, refresh_token: str) -> None:
    resp.set_cookie(
        SESSION_COOKIE,
        access_token,
        max_age=config.session_ttl_min * 60,
        path="/",
        domain=_domain(),
        secure=config.cookie_secure,
        httponly=True,
        samesite="Lax",
    )
    resp.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=config.refresh_ttl_days * 24 * 3600,
        path=REFRESH_PATH,
        domain=None,
        secure=config.cookie_secure,
        httponly=True,
        samesite="Lax",
    )


def clear_session_cookies(resp: Response) -> None:
    resp.delete_cookie(SESSION_COOKIE, path="/", domain=_domain(), secure=config.cookie_secure, httponly=True, samesite="Lax")
    resp.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, domain=None, secure=config.cookie_secure, httponly=True, samesite="Lax")
