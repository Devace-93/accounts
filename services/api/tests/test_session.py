import time
import uuid

import jwt
from conftest import cookie

from dbcore.keys import keyring
from dbcore.tokens import session_claims


def _expired_token_for(user_json: str, sid: str) -> str:
    class U:  # minimal stand-in for the ORM user
        id = uuid.UUID(user_json["id"])
        email = user_json["email"]
        email_verified_at = None
        handle = user_json["handle"]
        name = user_json["name"]
        avatar_version = 0

    claims = session_claims(U, sid, now=int(time.time()) - 3600)
    ring = keyring()
    return jwt.encode(claims, ring.private_key, algorithm="EdDSA", headers={"kid": ring.kid})


def test_session_requires_cookie_or_bearer(client, signup):
    r = client.get("/api/session")
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "no_session"

    user = signup()
    r = client.get("/api/session")
    assert r.status_code == 200
    body = r.get_json()
    assert body["user"]["id"] == user["id"] and body["session"]["expires_at"].endswith("Z")

    token = cookie(client, "3m4_session").value
    client.delete_cookie("3m4_session")
    assert client.get("/api/session").status_code == 401
    r = client.get("/api/session", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert client.get("/api/session", headers={"Authorization": "Bearer garbage"}).get_json()["error"]["code"] == "invalid_session"


def test_expired_access_token_is_session_expired(client, signup):
    user = signup()
    sid = client.get("/api/session").get_json()["session"]["id"]
    bad = _expired_token_for(user, sid)
    client.delete_cookie("3m4_session")  # the cookie wins over the bearer header when both are present
    r = client.get("/api/session", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "session_expired"


def test_refresh_rotates_and_rejects_reuse(client, signup):
    signup()
    old_access = cookie(client, "3m4_session").value
    old_refresh = cookie(client, "3m4_refresh", path="/api/session").value
    time.sleep(1.1)  # new iat → different JWT
    r = client.post("/api/session/refresh")
    assert r.status_code == 200 and r.get_json()["user"]["handle"] == "ana"
    new_access = cookie(client, "3m4_session").value
    new_refresh = cookie(client, "3m4_refresh", path="/api/session").value
    assert new_access != old_access and new_refresh != old_refresh
    # the same sid survives the rotation
    assert jwt.decode(new_access, options={"verify_signature": False})["sid"] == jwt.decode(old_access, options={"verify_signature": False})["sid"]

    client.set_cookie("3m4_refresh", old_refresh, path="/api/session")
    r = client.post("/api/session/refresh")
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "invalid_refresh"
    assert cookie(client, "3m4_session") is None  # cleared


def test_refresh_without_cookie(client):
    r = client.post("/api/session/refresh")
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "invalid_refresh"


def test_logout_clears_and_revokes(client, signup):
    signup()
    access = cookie(client, "3m4_session").value
    r = client.post("/api/session/logout", json={})
    assert r.status_code == 204
    assert cookie(client, "3m4_session") is None and cookie(client, "3m4_refresh", path="/api/session") is None
    # the old (still unexpired) JWT no longer passes accounts' own liveness check
    r = client.get("/api/session", headers={"Authorization": f"Bearer {access}"})
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "session_expired"


def test_logout_all_and_session_list(app, client, signup):
    signup()
    other = app.test_client()
    other.post("/api/auth/login", json={"email": "ana@example.com", "password": "correct horse battery"})
    items = client.get("/api/session/list").get_json()["items"]
    assert len(items) == 2 and sum(i["current"] for i in items) == 1
    assert other.get("/api/session").status_code == 200

    other_id = next(i["id"] for i in items if not i["current"])
    assert client.delete(f"/api/session/{other_id}").status_code == 204
    assert other.get("/api/session").get_json()["error"]["code"] == "session_expired"
    assert client.delete(f"/api/session/{other_id}").status_code == 204  # idempotent
    assert client.delete(f"/api/session/{uuid.uuid4()}").status_code == 404

    third = app.test_client()
    third.post("/api/auth/login", json={"email": "ana@example.com", "password": "correct horse battery"})
    assert client.post("/api/session/logout", json={"all": True}).status_code == 204
    assert third.get("/api/session").get_json()["error"]["code"] == "session_expired"


def test_logout_requires_json_content_type(client, signup):
    signup()
    assert client.post("/api/session/logout", data="x").status_code == 415
