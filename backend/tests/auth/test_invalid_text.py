import json

import pytest

from .conftest import PASSWORD, csrf


@pytest.mark.parametrize(
    "field,value",
    [
        ("username", "bad\u0000name"),
        ("display_name", "bad\u0000name"),
        ("password", "long-password-\ud800"),
    ],
)
def test_unsupported_registration_text_is_sanitized_422(client, field, value):
    body = {
        "username": "malformed-user",
        "display_name": "用户",
        "password": PASSWORD,
        field: value,
    }
    response = client.post(
        "/api/v1/auth/register",
        content=json.dumps(body),
        headers={**csrf(client), "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert PASSWORD not in response.text


def test_unsupported_login_password_is_sanitized_422(client, user):
    response = client.post(
        "/api/v1/auth/login",
        content=json.dumps({"username": user["username"], "password": "long-password-\ud800"}),
        headers={**csrf(client), "Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_admin_cannot_persist_nul_display_name(client, admin):
    response = client.patch(
        f"/api/v1/admin/users/{admin['id']}",
        content=json.dumps({"display_name": "bad\u0000name"}),
        headers={**csrf(client), "Content-Type": "application/json"},
    )
    assert response.status_code == 422
