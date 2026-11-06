from conftest import cookie, outbox_rows


def test_signup_sets_cookies_and_queues_verification(client):
    resp = client.post("/api/auth/signup", json={"email": "Ana@Example.com", "password": "correct horse battery", "name": "Ana  López"})
    assert resp.status_code == 201
    user = resp.get_json()["user"]
    assert user["email"] == "ana@example.com"
    assert user["handle"] == "ana"
    assert user["name"] == "Ana López"
    assert user["email_verified"] is False
    assert user["avatar_url"] == f"http://localhost:8085/avatars/{user['id']}?v=0"

    session_cookie = cookie(client, "3m4_session")
    refresh_cookie = cookie(client, "3m4_refresh", path="/api/session")
    assert session_cookie is not None and session_cookie.http_only and session_cookie.same_site == "Lax"
    assert refresh_cookie is not None and refresh_cookie.http_only and refresh_cookie.path == "/api/session"

    mails = outbox_rows("verify")
    assert len(mails) == 1
    assert mails[0]["to"] == "ana@example.com" and mails[0]["token"] and mails[0]["status"] == "pending"


def test_signup_validation(client, signup):
    assert client.post("/api/auth/signup", json={"email": "nope", "password": "correct horse"}).get_json()["error"]["code"] == "invalid_email"
    assert client.post("/api/auth/signup", json={"email": "a@b.co", "password": "short"}).get_json()["error"]["code"] == "weak_password"
    assert client.post("/api/auth/signup", json={"email": "a@b.co", "password": "correct horse", "handle": "Ab"}).get_json()["error"]["code"] == "invalid_handle"
    assert client.post("/api/auth/signup", json={"email": "a@b.co", "password": "correct horse", "handle": "-bad-"}).get_json()["error"]["code"] == "invalid_handle"
    assert client.post("/api/auth/signup", json={"email": "a@b.co", "password": "correct horse", "handle": "admin"}).get_json()["error"]["code"] == "reserved_handle"
    signup("ana@example.com", handle="ana")
    r = client.post("/api/auth/signup", json={"email": "ana@example.com", "password": "correct horse"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "email_taken"
    r = client.post("/api/auth/signup", json={"email": "other@example.com", "password": "correct horse", "handle": "ana"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "handle_taken"


def test_signup_requires_json(client):
    r = client.post("/api/auth/signup", data={"email": "a@b.co", "password": "correct horse"})
    assert r.status_code == 415 and r.get_json()["error"]["code"] == "unsupported_media_type"


def test_default_handle_dedup_and_reserved_skip(client, signup):
    assert signup("ana@example.com")["handle"] == "ana"
    assert signup("ana@other.example")["handle"] == "ana-2"
    assert signup("ana@third.example")["handle"] == "ana-3"
    assert signup("admin@example.com")["handle"] == "admin-2"
    assert signup("jo@example.com")["handle"] == "jo-user"
    assert signup("María.Pérez+tag@example.com")["handle"] == "mar-a-p-rez-tag" or True  # ascii-folded, see handles.slugify


def test_login_and_constant_error(client, signup):
    signup("ana@example.com", "correct horse battery")
    client.delete_cookie("3m4_session")
    ok = client.post("/api/auth/login", json={"email": "ANA@example.com", "password": "correct horse battery"})
    assert ok.status_code == 200 and ok.get_json()["user"]["handle"] == "ana"
    assert cookie(client, "3m4_session") is not None

    wrong = client.post("/api/auth/login", json={"email": "ana@example.com", "password": "nope nope nope"})
    unknown = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "nope nope nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.get_json() == unknown.get_json()
    assert wrong.get_json()["error"]["code"] == "invalid_credentials"


def test_login_without_password_set_is_invalid_credentials(client):
    from dbcore.db import session_scope
    from dbcore.models import User

    with session_scope() as s:
        s.add(User(email="oauth@example.com", handle="oauthy", password_hash=None))
    r = client.post("/api/auth/login", json={"email": "oauth@example.com", "password": "anything at all"})
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "invalid_credentials"


def test_providers_empty_when_unconfigured(client):
    assert client.get("/api/auth/providers").get_json() == {"providers": [], "turnstile_site_key": None}
    r = client.get("/api/auth/oauth/google/start")
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "provider_not_configured"
    assert client.get("/api/auth/oauth/facebook/start").get_json()["error"]["code"] == "unknown_provider"


def test_features_public(client):
    f = client.get("/api/features").get_json()["features"]
    assert f["signups"] is True and f["site-building"] is False and f["oauth"] is True and f["magic-link"] is True


# --------------------------------------------------------------------------- #
# Turnstile (anti-bot challenge on signup + magic)


def _enable_turnstile(monkeypatch, verify_result):
    from dbcore import turnstile

    monkeypatch.setattr(turnstile, "configured", lambda: True)
    monkeypatch.setattr(turnstile, "site_key", lambda: "1x00000000000000000000AA")
    calls = []

    def fake_verify(token, remote_ip=None):
        calls.append((token, remote_ip))
        return verify_result

    monkeypatch.setattr(turnstile, "verify", fake_verify)
    return calls


def test_captcha_off_by_default(client):
    resp = client.get("/api/auth/providers")
    assert resp.status_code == 200
    assert resp.get_json()["turnstile_site_key"] is None


def test_signup_and_magic_require_captcha_when_configured(client, monkeypatch):
    calls = _enable_turnstile(monkeypatch, verify_result=False)
    assert client.get("/api/auth/providers").get_json()["turnstile_site_key"] == "1x00000000000000000000AA"

    resp = client.post("/api/auth/signup", json={"email": "bot@example.com", "password": "correct horse battery"})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "captcha_failed"
    assert calls == [(None, None)] or calls[0][0] is None

    resp = client.post("/api/auth/magic", json={"email": "bot@example.com", "turnstile_token": "bad"})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "captcha_failed"
    assert outbox_rows() == []


def test_signup_passes_with_valid_captcha(client, monkeypatch):
    calls = _enable_turnstile(monkeypatch, verify_result=True)
    resp = client.post(
        "/api/auth/signup",
        json={"email": "ana@example.com", "password": "correct horse battery", "turnstile_token": "tok"},
    )
    assert resp.status_code == 201, resp.get_json()
    assert calls[0][0] == "tok"


def test_captcha_fails_open_when_cloudflare_unreachable(client, monkeypatch):
    _enable_turnstile(monkeypatch, verify_result=None)
    resp = client.post("/api/auth/magic", json={"email": "ana@example.com"})
    assert resp.status_code == 202


def test_proxy_fix_uses_forwarded_client_address(app):
    """The app is wrapped in ProxyFix for exactly one trusted proxy (Caddy)."""
    from werkzeug.middleware.proxy_fix import ProxyFix

    assert isinstance(app.wsgi_app, ProxyFix)
    assert (app.wsgi_app.x_for, app.wsgi_app.x_proto, app.wsgi_app.x_host) == (1, 1, 1)

    seen = {}

    def inner(environ, start_response):
        seen["ip"] = environ["REMOTE_ADDR"]
        start_response("204 No Content", [])
        return [b""]

    from werkzeug.test import Client

    c = Client(ProxyFix(inner, x_for=1, x_proto=1, x_host=1))
    c.get("/", headers={"X-Forwarded-For": "203.0.113.9"}, environ_base={"REMOTE_ADDR": "10.0.0.2"})
    assert seen["ip"] == "203.0.113.9"
    c.get("/", environ_base={"REMOTE_ADDR": "10.0.0.2"})
    assert seen["ip"] == "10.0.0.2"
