"""Cloudflare Turnstile verification for the anonymous write endpoints
(``POST /auth/signup``, ``POST /auth/magic``).

Enabled when ``TURNSTILE_SITE_KEY`` and ``TURNSTILE_SECRET`` are both set; the
pages fetch the site key from ``GET /api/auth/providers`` and send the widget's
token as ``turnstile_token``. :func:`verify` returns ``True`` (valid),
``False`` (missing / invalid) or ``None`` when Cloudflare could not be reached,
so the caller can decide to fail open (the sign-up page must not depend on a
third party being up).
"""
from __future__ import annotations

import json
import logging
from urllib import error, parse, request

from .config import config

log = logging.getLogger("accounts.turnstile")

TIMEOUT_SECONDS = 5


def configured() -> bool:
    return bool(config.turnstile_site_key and config.turnstile_secret)


def site_key() -> str | None:
    """The public site key the pages render the widget with (None = off)."""
    return config.turnstile_site_key if configured() else None


def verify(token: str | None, remote_ip: str | None = None) -> bool | None:
    if not token:
        return False
    body = {"secret": config.turnstile_secret, "response": token}
    if remote_ip:
        body["remoteip"] = remote_ip
    req = request.Request(
        config.turnstile_verify_url,
        data=parse.urlencode(body).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "accounts/1"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode() or "{}")
    except (error.URLError, OSError, ValueError) as err:
        log.warning("turnstile verification unavailable: %s", err)
        return None
    return bool(data.get("success"))
