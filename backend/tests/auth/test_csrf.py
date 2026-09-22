from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from .conftest import csrf, login, register


@pytest.mark.parametrize("headers", [{}, {"X-CSRF-Token": "forged", "Origin": "http://testserver"}])
def test_writes_require_csrf(client, headers):
    response = client.post("/api/v1/auth/register", json={}, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


@pytest.mark.parametrize(
    "origin", ["https://evil.invalid", "http://testserver.evil.invalid", "null"]
)
def test_cross_origin_write_is_rejected(client, origin):
    headers = {**csrf(client), "Origin": origin}
    assert client.post("/api/v1/auth/login", json={}, headers=headers).status_code == 403


def test_origin_or_same_origin_referer_required(client):
    headers = csrf(client)
    headers.pop("Origin")
    assert client.post("/api/v1/auth/login", json={}, headers=headers).status_code == 403
    headers["Referer"] = "http://testserver/login"
    assert client.post("/api/v1/auth/login", json={}, headers=headers).status_code == 422


def test_tokens_bound_to_cookie_and_login_rotation(client, user, auth_app):
    before = csrf(client)
    with TestClient(auth_app) as other:
        other.get("/api/v1/auth/csrf")
        assert other.post("/api/v1/auth/login", json={}, headers=before).status_code == 403
    assert login(client, user["username"]).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=before).status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200


def test_prelogin_expiry(client, auth_app):
    before = csrf(client)
    now = auth_app.state.auth_clock()
    auth_app.state.auth_clock = lambda: now + timedelta(minutes=11)
    assert client.post("/api/v1/auth/login", json={}, headers=before).status_code == 403
    assert csrf(client)["X-CSRF-Token"] != before["X-CSRF-Token"]


def test_global_guard_covers_multipart_and_logout(client, auth_app, signed_in):
    @auth_app.post("/api/v1/test-upload")
    def upload():
        return {"accepted": True}

    assert (
        client.post("/api/v1/test-upload", files={"file": ("test.txt", b"test")}).status_code == 403
    )
    assert client.post(
        "/api/v1/test-upload", headers=csrf(client), files={"file": ("test.txt", b"test")}
    ).json() == {"accepted": True}
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200


def test_production_cookies_secure_and_responses_not_cached(auth_app):
    auth_app.state.settings.app_env = "production"
    auth_app.state.settings.public_origin = "https://testserver"
    with TestClient(auth_app, base_url="https://testserver") as client:
        prelogin = client.get("/api/v1/auth/csrf")
        assert "Secure" in prelogin.headers["set-cookie"]
        user = register(client).json()
        response = login(client, user["username"])
        assert response.status_code == 200
        assert "Secure" in response.headers["set-cookie"]
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/v1/auth/csrf").headers["cache-control"] == "no-store"


def test_non_ascii_forged_token_is_rejected_not_internal_error(client):
    csrf(client)
    response = client.post(
        "/api/v1/auth/login",
        json={},
        headers={b"Origin": b"http://testserver", b"X-CSRF-Token": b"\xe9" * 64},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


def test_raw_non_ascii_csrf_header_is_rejected(client, auth_app):
    from fastapi import Request

    from app.core.security import AuthError
    from app.modules.auth.service import check_csrf

    csrf(client)
    # TestClient's header encoding changes byte counts; retain the actual wire/ASGI bytes.
    request = Request(
        {
            "type": "http",
            "app": auth_app,
            "scheme": "http",
            "method": "POST",
            "server": ("testserver", 80),
            "path": "/api/v1/auth/login",
            "query_string": b"",
            "headers": [
                (b"host", b"testserver"),
                (b"origin", b"http://testserver"),
                (b"cookie", ("qa_prelogin=" + client.cookies.get("qa_prelogin")).encode()),
                (b"x-csrf-token", b"\xe9" * 64),
            ],
        }
    )
    with pytest.raises(AuthError) as error:
        check_csrf(request)
    assert error.value.status == 403
