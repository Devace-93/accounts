import io

from conftest import outbox_rows
from PIL import Image

from dbcore.db import session_scope
from dbcore.models import Identity, User


def _png(w=400, h=300, colour=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def test_me_and_patch(client, signup):
    signup(handle="ana", name="Ana")
    me = client.get("/api/me").get_json()
    assert me["has_password"] is True and me["identities"] == [] and me["user"]["handle"] == "ana"

    r = client.patch("/api/me", json={"name": "  Ana   María ", "handle": "ana-maria"})
    assert r.status_code == 200
    assert r.get_json()["user"]["name"] == "Ana María" and r.get_json()["user"]["handle"] == "ana-maria"
    assert client.patch("/api/me", json={"handle": "ADMIN"}).get_json()["error"]["code"] == "reserved_handle"
    assert client.patch("/api/me", json={"handle": "x"}).get_json()["error"]["code"] == "invalid_handle"
    assert client.patch("/api/me", json={"name": "x" * 81}).get_json()["error"]["code"] == "invalid_name"
    assert client.patch("/api/me", json={"name": None}).get_json()["user"]["name"] is None
    # keeping your own handle is fine; taking someone else's is not
    assert client.patch("/api/me", json={"handle": "ana-maria"}).status_code == 200
    signup("bob@example.com", handle="bob")
    client.post("/api/auth/login", json={"email": "ana@example.com", "password": "correct horse battery"})
    r = client.patch("/api/me", json={"handle": "bob"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "handle_taken"
    # the new handle shows up in freshly issued claims
    client.patch("/api/me", json={"handle": "ana-new"})
    assert client.post("/api/session/refresh").get_json()["user"]["handle"] == "ana-new"


def test_password_change_revokes_other_sessions(app, client, signup):
    signup()
    other = app.test_client()
    other.post("/api/auth/login", json={"email": "ana@example.com", "password": "correct horse battery"})
    assert other.get("/api/session").status_code == 200

    r = client.put("/api/me/password", json={"current_password": "wrong wrong wrong", "new_password": "brand new password"})
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "invalid_credentials"
    r = client.put("/api/me/password", json={"current_password": "correct horse battery", "new_password": "short"})
    assert r.get_json()["error"]["code"] == "weak_password"
    r = client.put("/api/me/password", json={"current_password": "correct horse battery", "new_password": "brand new password"})
    assert r.status_code == 204

    assert client.get("/api/session").status_code == 200  # the current session survives
    assert other.get("/api/session").get_json()["error"]["code"] == "session_expired"
    assert client.post("/api/auth/login", json={"email": "ana@example.com", "password": "brand new password"}).status_code == 200
    assert outbox_rows("password_changed")[-1]["to"] == "ana@example.com"


def test_set_password_when_none(client):
    with session_scope() as s:
        s.add(User(email="oauth@example.com", handle="oauthy", password_hash=None))
    # log in by magic link to get a session
    client.post("/api/auth/magic", json={"email": "oauth@example.com"})
    token = outbox_rows("magic")[-1]["token"]
    client.post("/api/auth/magic/consume", json={"token": token})
    assert client.get("/api/me").get_json()["has_password"] is False
    assert client.put("/api/me/password", json={"new_password": "first password ever"}).status_code == 204
    assert client.get("/api/me").get_json()["has_password"] is True


def test_avatar_upload_default_etag_and_delete(client, signup):
    user = signup(name="Ana López")
    uid = user["id"]

    r = client.get(f"/avatars/{uid}")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml" and b">AL<" in r.data
    assert r.headers["Cache-Control"] == "public, max-age=86400" and r.headers["Access-Control-Allow-Origin"] == "*"
    etag = r.headers["ETag"]
    assert client.get(f"/avatars/{uid}", headers={"If-None-Match": etag}).status_code == 304

    r = client.put("/api/me/avatar", data={"file": (io.BytesIO(_png()), "me.png")}, content_type="multipart/form-data")
    assert r.status_code == 403 and r.get_json()["error"]["code"] == "csrf_check_failed"
    hdr = {"X-Requested-With": "3m4"}
    r = client.put("/api/me/avatar", data={"file": (io.BytesIO(b"not an image"), "x.png")}, content_type="multipart/form-data", headers=hdr)
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "invalid_image"
    r = client.put("/api/me/avatar", data={"file": (io.BytesIO(_png()), "me.png")}, content_type="multipart/form-data", headers=hdr)
    assert r.status_code == 200
    assert r.get_json()["user"]["avatar_url"].endswith("?v=1")

    r = client.get(f"/avatars/{uid}")
    assert r.mimetype == "image/webp" and r.headers["ETag"] != etag
    img = Image.open(io.BytesIO(r.data))
    assert img.size == (256, 256) and img.format == "WEBP"
    assert client.get(f"/avatars/{uid}", headers={"If-None-Match": r.headers["ETag"]}).status_code == 304

    r = client.delete("/api/me/avatar")
    assert r.status_code == 200 and r.get_json()["user"]["avatar_url"].endswith("?v=2")
    assert client.get(f"/avatars/{uid}").mimetype == "image/svg+xml"
    assert client.get("/avatars/not-a-uuid").status_code == 404
    assert client.get("/avatars/00000000-0000-0000-0000-000000000000").status_code == 404


def test_avatar_too_large(client, signup):
    signup()
    big = b"\x89PNG" + b"\x00" * (2 * 1024 * 1024 + 10)
    r = client.put("/api/me/avatar", data={"file": (io.BytesIO(big), "big.png")}, content_type="multipart/form-data", headers={"X-Requested-With": "3m4"})
    assert r.status_code in (413, 400)


def test_unlink_identity_guard(client, signup):
    user = signup()
    assert client.delete("/api/me/identities/github").status_code == 404
    with session_scope() as s:
        s.add(Identity(user_id=user["id"], provider="github", provider_user_id="1", provider_email="ana@example.com"))
    assert client.get("/api/me").get_json()["identities"][0]["provider"] == "github"
    assert client.delete("/api/me/identities/github").status_code == 204  # has a password: fine

    with session_scope() as s:
        u = s.get(User, user["id"])
        u.password_hash = None
        s.add(Identity(user_id=u.id, provider="google", provider_user_id="g1", provider_email="ana@example.com"))
    r = client.delete("/api/me/identities/google")
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "last_login_method"
    with session_scope() as s:
        s.add(Identity(user_id=user["id"], provider="discord", provider_user_id="d1"))
    assert client.delete("/api/me/identities/google").status_code == 204
