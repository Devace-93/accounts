from datetime import datetime, timedelta, timezone

from conftest import cookie, outbox_rows
from sqlalchemy import select, update

from dbcore import worker
from dbcore.db import session_scope
from dbcore.mail_templates import render
from dbcore.models import EmailToken, Outbox


def test_magic_request_consume_verifies_and_logs_in(client, signup, latest_token):
    signup()
    client.post("/api/session/logout", json={})
    r = client.post("/api/auth/magic", json={"email": "ana@example.com", "return_to": "https://metrics.3m4.net/dashboard"})
    assert r.status_code == 202
    token = latest_token("magic")
    mail = outbox_rows("magic")[-1]
    assert mail["return_to"] == "https://metrics.3m4.net/dashboard"

    subject, text, html = render("magic", lang="es", to="ana@example.com", token=token, return_to=mail["return_to"])
    link = f"http://localhost:8085/magic?token={token}&return_to=https%3A%2F%2Fmetrics.3m4.net%2Fdashboard"
    assert link in text and link.replace("&", "&amp;") in html and "entrar" in subject.lower()
    # without return_to the link has no '&' and is byte-identical in both parts
    _, text2, html2 = render("magic", lang="en", to="ana@example.com", token=token)
    assert f"http://localhost:8085/magic?token={token}" in text2 and f'href="http://localhost:8085/magic?token={token}"' in html2

    assert client.get("/api/auth/magic/consume").status_code == 405  # a GET never consumes
    r = client.post("/api/auth/magic/consume", json={"token": token})
    assert r.status_code == 200
    body = r.get_json()
    assert body["user"]["email_verified"] is True and body["return_to"] == "https://metrics.3m4.net/dashboard"
    assert cookie(client, "3m4_session") is not None
    assert client.get("/api/session").status_code == 200

    r = client.post("/api/auth/magic/consume", json={"token": token})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "used_token"


def test_magic_unknown_email_is_silent_and_mails_signup_hint(client):
    r = client.post("/api/auth/magic", json={"email": "ghost@example.com"})
    assert r.status_code == 202 and r.get_json() == {}
    rows = outbox_rows("magic_no_account")
    assert rows and rows[0]["to"] == "ghost@example.com" and rows[0]["token"] is None
    _, text, html = render("magic_no_account", lang="en", to="ghost@example.com")
    assert "http://localhost:8085/signup" in text and "http://localhost:8085/signup" in html


def test_magic_bad_return_to_falls_back(client, signup, latest_token):
    signup()
    client.post("/api/auth/magic", json={"email": "ana@example.com", "return_to": "https://evil.example/phish"})
    r = client.post("/api/auth/magic/consume", json={"token": latest_token("magic")})
    assert r.get_json()["return_to"] == "http://localhost:8085/profile"


def test_token_expiry_and_garbage(client, signup, latest_token):
    signup()
    client.post("/api/auth/magic", json={"email": "ana@example.com"})
    token = latest_token("magic")
    with session_scope() as s:
        s.execute(update(EmailToken).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    r = client.post("/api/auth/magic/consume", json={"token": token})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "expired_token"
    assert client.post("/api/auth/magic/consume", json={"token": "nope"}).get_json()["error"]["code"] == "invalid_token"
    assert client.post("/api/auth/magic/consume", json={}).get_json()["error"]["code"] == "invalid_token"
    # a verify token cannot be used as a magic token
    verify_token = latest_token("verify")
    assert client.post("/api/auth/magic/consume", json={"token": verify_token}).get_json()["error"]["code"] == "invalid_token"


def test_new_token_invalidates_previous(client, signup, latest_token):
    signup()
    client.post("/api/auth/magic", json={"email": "ana@example.com"})
    first = latest_token("magic")
    client.post("/api/auth/magic", json={"email": "ana@example.com"})
    second = latest_token("magic")
    assert first != second
    assert client.post("/api/auth/magic/consume", json={"token": first}).get_json()["error"]["code"] == "invalid_token"
    assert client.post("/api/auth/magic/consume", json={"token": second}).status_code == 200


def test_verify_consume_and_resend(app, client, signup, latest_token):
    user = signup()
    assert client.get("/api/session").get_json()["user"]["email_verified"] is False
    token = latest_token("verify")
    # consuming from a browser without a session works too
    anon = app.test_client()
    r = anon.post("/api/auth/verify/consume", json={"token": token})
    assert r.status_code == 200 and r.get_json()["user"]["email_verified"] is True
    assert cookie(anon, "3m4_session") is None  # verification does not log in
    assert client.get("/api/session").get_json()["user"]["email_verified"] is True  # claims are re-read from the DB
    assert client.post("/api/auth/verify/consume", json={"token": token}).get_json()["error"]["code"] == "used_token"
    r = client.post("/api/auth/verify/resend", json={})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "already_verified"
    assert anon.post("/api/auth/verify/resend", json={}).status_code == 401
    assert user["id"]


def test_verify_resend_queues_new_mail(client, signup, latest_token):
    signup()
    first = latest_token("verify")
    assert client.post("/api/auth/verify/resend", json={"lang": "es"}).status_code == 202
    rows = outbox_rows("verify")
    assert len(rows) == 2 and rows[-1]["lang"] == "es" and rows[-1]["token"] != first
    subject, text, html = render("verify", lang="es", to="ana@example.com", token=rows[-1]["token"])
    assert f"http://localhost:8085/verify?token={rows[-1]['token']}" in text and "Confirma" in subject


def test_worker_skips_when_mail_disabled(client, signup):
    signup()
    counts = worker.drain()
    assert counts == {"skipped": 1}
    with session_scope() as s:
        row = s.scalar(select(Outbox))
        assert row.status == "skipped" and row.attempts == 1 and row.sent_at is not None


def test_lang_fallback_in_templates():
    subject_en, _, _ = render("verify", lang="fr", to="x@example.com", token="t")
    subject_default, _, _ = render("verify", lang="en", to="x@example.com", token="t")
    assert subject_en == subject_default
    subject, text, html = render("password_changed", lang="en", to="x@example.com", name="Ana")
    assert "Ana" in text and "http://localhost:8085/profile" in html and "password" in subject


def test_verify_consume_reissues_the_callers_session(app, client, signup, latest_token):
    """Relying apps read the claims, not the DB: verifying from the browser that
    signed up must hand it a fresh JWT with email_verified=true immediately."""
    import jwt

    signup()
    old = cookie(client, "3m4_session").value
    assert jwt.decode(old, options={"verify_signature": False})["email_verified"] is False
    r = client.post("/api/auth/verify/consume", json={"token": latest_token("verify")})
    assert r.status_code == 200
    new = cookie(client, "3m4_session").value
    assert new != old
    claims = jwt.decode(new, options={"verify_signature": False})
    assert claims["email_verified"] is True
    assert cookie(client, "3m4_refresh", path="/api/session") is not None
    # another browser's session is left alone
    signup(email="bob@example.com")
    other = app.test_client()
    r = other.post("/api/auth/verify/consume", json={"token": latest_token("verify")})
    assert r.status_code == 200 and cookie(other, "3m4_session") is None
