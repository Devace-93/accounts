import uuid

import m4session
import pytest
from conftest import cookie

from api.blueprints.oauth import OAuthFailure, ProviderProfile, complete
from api.returns import safe_return_to
from dbcore.db import session_scope
from dbcore.models import Avatar, Identity, User
from dbcore.origins import OriginMatcher, matcher


def test_jwks_shape(client):
    r = client.get("/.well-known/jwks.json")
    assert r.status_code == 200 and r.headers["Cache-Control"] == "public, max-age=600"
    key = r.get_json()["keys"][0]
    assert key["kty"] == "OKP" and key["crv"] == "Ed25519" and key["alg"] == "EdDSA" and key["use"] == "sig"
    assert len(key["kid"]) == 8 and key["x"]


def test_relying_party_verifies_with_jwks(client, signup, monkeypatch):
    user = signup(handle="ana", name="Ana")
    token = cookie(client, "3m4_session").value
    jwks = client.get("/.well-known/jwks.json").get_json()

    class FakeResp:
        def json(self):
            return jwks

    calls = []
    monkeypatch.setattr(m4session.requests, "get", lambda url, timeout: calls.append(url) or FakeResp())
    m4session._cache._keys.clear()

    claims = m4session.verify(token, jwks_url="http://localhost:8085/.well-known/jwks.json", issuer="http://localhost:8085/")
    assert claims["sub"] == user["id"] and claims["handle"] == "ana" and claims["email_verified"] is False
    assert claims["avatar_url"].endswith("?v=0") and claims["aud"] == "3m4"
    # second verification hits the cache
    m4session.verify(token, jwks_url="http://localhost:8085/.well-known/jwks.json", issuer="http://localhost:8085")
    assert len(calls) == 1

    with pytest.raises(m4session.SessionError) as err:
        m4session.verify(token, jwks_url="http://localhost:8085/.well-known/jwks.json", issuer="https://someone-else.example")
    assert err.value.code == "invalid_session"
    with pytest.raises(m4session.SessionError) as err:
        m4session.verify("", jwks_url="x", issuer="y")
    assert err.value.code == "no_session"
    with pytest.raises(m4session.SessionError) as err:
        m4session.verify(token + "x", jwks_url="http://localhost:8085/.well-known/jwks.json", issuer="http://localhost:8085")
    assert err.value.code == "invalid_session"


def test_relying_party_flask_decorator(client, signup):
    from flask import Flask, g, jsonify

    signup()
    token = cookie(client, "3m4_session").value
    jwks = client.get("/.well-known/jwks.json").get_json()

    class FakeResp:
        def json(self):
            return jwks

    m4session.requests.get = lambda url, timeout: FakeResp()
    m4session._cache._keys.clear()

    class AppError(Exception):
        def __init__(self, status, code, message):
            self.status, self.code = status, code

    app = Flask("rp")
    require_session = m4session.flask_require_session("http://localhost:8085", on_error=AppError)

    @app.errorhandler(AppError)
    def handle(err):
        return jsonify({"error": {"code": err.code}}), err.status

    @app.get("/me")
    @require_session
    def me():
        return jsonify({"sub": g.identity["sub"]})

    @app.get("/verified")
    @require_session
    @m4session.require_verified(on_error=AppError)
    def verified():
        return jsonify({"ok": True})

    rp = app.test_client()
    assert rp.get("/me").get_json()["error"]["code"] == "no_session"
    rp.set_cookie("3m4_session", token)
    assert rp.get("/me").status_code == 200
    r = rp.get("/verified")
    assert r.status_code == 403 and r.get_json()["error"]["code"] == "email_unverified"
    rp.delete_cookie("3m4_session")
    assert rp.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_return_to_guard():
    assert safe_return_to("https://metrics.3m4.net/dashboard?x=1") == "https://metrics.3m4.net/dashboard?x=1"
    assert safe_return_to("https://3m4.net/") == "https://3m4.net/"
    assert safe_return_to("http://localhost:4321/") == "http://localhost:4321/"
    assert safe_return_to("/profile?tab=sessions") == "http://localhost:8085/profile?tab=sessions"
    for bad in (None, "", "https://evil.example/", "https://3m4.net.evil.example/", "https://a.b.3m4.net/", "//evil.example",
                "javascript:alert(1)", "ftp://3m4.net/", "https://metrics.3m4.net:8443@evil.example/", "x" * 3000):
        assert safe_return_to(bad) == "http://localhost:8085/profile", bad


def test_origin_matcher():
    assert matcher.allows("https://app.3m4.net") and matcher.allows("https://3m4.net") and matcher.allows("HTTPS://Retro.3m4.net/")
    assert matcher.allows("http://localhost:4321") and matcher.allows("http://localhost") and matcher.allows("http://127.0.0.1:8080")
    for bad in ("https://evil.example", "https://3m4.net.evil.example", "https://a.b.3m4.net", "http://app.3m4.net", "null", "", None):
        assert not matcher.allows(bad), bad
    custom = OriginMatcher(["https://*.example.org:8443"])
    assert custom.allows("https://x.example.org:8443") and not custom.allows("https://x.example.org")


def test_cors_headers(client, signup):
    signup()
    r = client.get("/api/session", headers={"Origin": "https://metrics.3m4.net"})
    assert r.headers["Access-Control-Allow-Origin"] == "https://metrics.3m4.net"
    assert r.headers["Access-Control-Allow-Credentials"] == "true" and "Origin" in r.headers.get("Vary", "")
    r = client.get("/api/session", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200 and "Access-Control-Allow-Origin" not in r.headers
    r = client.options("/api/session/logout", headers={"Origin": "https://bubbles.3m4.net", "Access-Control-Request-Method": "POST",
                                                        "Access-Control-Request-Headers": "content-type"})
    assert r.status_code < 300 and r.headers["Access-Control-Allow-Origin"] == "https://bubbles.3m4.net"
    assert "POST" in r.headers["Access-Control-Allow-Methods"] and r.headers["Access-Control-Allow-Headers"] == "content-type"
    r = client.options("/api/session/logout", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "Access-Control-Allow-Origin" not in r.headers
    # public endpoints stay open to everyone
    assert client.get("/.well-known/jwks.json", headers={"Origin": "https://evil.example"}).headers["Access-Control-Allow-Origin"] == "*"


# --------------------------------------------------------------------------- #
# OAuth rules (no network: drive `complete` with fake provider profiles)
# --------------------------------------------------------------------------- #
def _profile(provider="github", uid="42", email="ana@example.com", verified=True, login="anadev", name="Ana", picture=None):
    return ProviderProfile(provider, uid, email, verified, name=name, login=login, picture=picture, raw={"id": uid})


def test_oauth_signup_login_and_handle(client):
    user, event = complete(_profile(), avatar_webp=b"RIFFfakewebp")
    assert event == "signup" and user.handle == "anadev" and user.email_verified_at is not None and user.password_hash is None
    with session_scope() as s:
        assert s.get(Avatar, user.id) is not None and s.get(User, user.id).avatar_version == 1
        assert s.query(Identity).filter_by(provider="github", provider_user_id="42").one().user_id == user.id
    again, event = complete(_profile(email="changed@example.com"))
    assert event == "login" and again.id == user.id
    # unverified provider e-mail still creates an account, just unverified
    u2, _ = complete(_profile(uid="43", email="bob@example.com", verified=False, login="anadev"))
    assert u2.email_verified_at is None and u2.handle == "anadev-2"


def test_oauth_links_known_email_only_when_verified(client, signup):
    existing = signup("ana@example.com")
    with pytest.raises(OAuthFailure) as err:
        complete(_profile(provider="discord", uid="d1", verified=False))
    assert err.value.code == "oauth_email_unverified"
    user, event = complete(_profile(provider="discord", uid="d1", verified=True))
    assert event == "login" and str(user.id) == existing["id"] and user.email_verified_at is not None
    with pytest.raises(OAuthFailure) as err:
        complete(_profile(provider="google", uid="g1", email=None))
    assert err.value.code == "oauth_no_email"


def test_oauth_link_mode(client, signup):
    ana = signup("ana@example.com")
    bob = signup("bob@example.com")
    user, event = complete(_profile(provider="google", uid="g9", email="ana.alt@example.com"), link_user_id=uuid.UUID(ana["id"]))
    assert event == "linked" and str(user.id) == ana["id"]
    with pytest.raises(OAuthFailure) as err:
        complete(_profile(provider="google", uid="g9"), link_user_id=uuid.UUID(bob["id"]))
    assert err.value.code == "identity_taken"
    # linking the same identity to the same user again is a no-op
    assert complete(_profile(provider="google", uid="g9"), link_user_id=uuid.UUID(ana["id"]))[1] == "linked"
    with pytest.raises(OAuthFailure) as err:
        complete(_profile(provider="google", uid="g10"), link_user_id=uuid.uuid4())
    assert err.value.code == "no_session"


def test_oauth_signups_disabled(client, monkeypatch):
    monkeypatch.setenv("FEATURE_FLAG_OVERRIDES", "signups=off")
    with pytest.raises(OAuthFailure) as err:
        complete(_profile(uid="99", email="new@example.com"))
    assert err.value.code == "signups_disabled"
    monkeypatch.setenv("FEATURE_FLAG_OVERRIDES", "")
    r = client.post("/api/auth/signup", json={"email": "x@example.com", "password": "correct horse battery"})
    assert r.status_code == 201
