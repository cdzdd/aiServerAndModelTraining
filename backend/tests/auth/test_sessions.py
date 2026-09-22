from datetime import timedelta

import pytest
from sqlalchemy import text

from .conftest import PASSWORD, csrf, login, register


def test_registration_login_and_private_session_storage(client, migrated_engine, caplog):
    response = register(client, username="  Alice  ")
    assert response.status_code == 201
    user = response.json()
    assert user["username"] == "alice" and user["role"] == "user"
    assert client.get("/api/v1/auth/me").status_code == 401
    response = login(client, "ALICE")
    assert response.status_code == 200
    assert response.json()["user"] == user
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=86400" in cookie
    token = client.cookies.get("qa_session")
    with migrated_engine.connect() as db:
        saved = db.execute(
            text("SELECT password_hash FROM users WHERE id=:id"), {"id": user["id"]}
        ).scalar_one()
        hashes = db.execute(text("SELECT token_hash FROM auth_sessions")).scalars().all()
    assert saved.startswith("$argon2id$")
    assert token not in hashes
    assert PASSWORD not in response.text + caplog.text
    assert saved not in response.text + caplog.text
    assert token not in response.text + caplog.text
    assert client.get("/api/v1/auth/me").json() == user


@pytest.mark.parametrize("extra", [{"role": "admin"}, {"role": "agent"}, {"is_active": True}])
def test_registration_cannot_choose_privileges(client, extra):
    response = register(client, **extra)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "field,value",
    [
        ("username", "aa"),
        ("username", "x" * 51),
        ("password", "x" * 11),
        ("password", "x" * 129),
        ("display_name", "  "),
    ],
)
def test_registration_validation_is_safe(client, field, value):
    response = register(client, **{field: value})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "password_hash" not in response.text


def test_duplicate_normalized_username(client, user):
    assert register(client, username=" " + user["username"].upper() + " ").status_code == 409


def test_login_wrong_unknown_and_inactive_have_identical_errors(client, user, migrated_engine):
    wrong = login(client, user["username"], "wrong-password-123")
    unknown = login(client, "unknown-account", "wrong-password-123")
    with migrated_engine.begin() as db:
        db.execute(text("UPDATE users SET is_active=false WHERE id=:id"), {"id": user["id"]})
    inactive = login(client, user["username"])
    for response in (wrong, unknown, inactive):
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "用户名或密码错误"
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_rotates_and_revokes_previous_session(client, signed_in):
    old_cookie = client.cookies.get("qa_session")
    assert login(client, signed_in["username"]).status_code == 200
    assert client.cookies.get("qa_session") != old_cookie
    client.cookies.clear()
    client.cookies.set("qa_session", old_cookie)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_revokes_replayed_cookie(client, signed_in):
    cookie = client.cookies.get("qa_session")
    assert client.post("/api/v1/auth/logout", headers=csrf(client)).status_code == 204
    assert client.cookies.get("qa_session") is None
    client.cookies.set("qa_session", cookie)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_expired_cookie_is_rejected_without_renewal(client, signed_in, auth_app):
    now = auth_app.state.auth_clock()
    assert "set-cookie" not in client.get("/api/v1/auth/me").headers
    auth_app.state.auth_clock = lambda: now + timedelta(hours=24, seconds=1)
    assert client.get("/api/v1/auth/me").status_code == 401
