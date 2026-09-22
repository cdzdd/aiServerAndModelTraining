import pytest


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"PUBLIC_ORIGIN": "http://qa.example"},
        {"PUBLIC_ORIGIN": "https://qa.example/path"},
        {"PUBLIC_ORIGIN": "https://user:pass@qa.example"},
    ],
)
def test_production_requires_explicit_https_origin(extra, tmp_path):
    from app.core.config import Settings

    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            APP_ENV="production",
            DATABASE_URL="postgresql+psycopg://test:hidden@localhost/test",
            SESSION_SECRET="test-only-secret-with-at-least-32-chars",
            UPLOAD_DIR=tmp_path,
            **extra,
        )


def test_production_rejects_short_secret(tmp_path):
    from app.core.config import Settings

    with pytest.raises(ValueError) as error:
        Settings(
            _env_file=None,
            APP_ENV="production",
            PUBLIC_ORIGIN="https://qa.example",
            DATABASE_URL="postgresql+psycopg://test:hidden@localhost/test",
            SESSION_SECRET="short",
            UPLOAD_DIR=tmp_path,
        )
    assert "hidden" not in str(error.value)


def test_configured_origin_used_instead_of_internal_proxy_host(client, auth_app):
    from .conftest import csrf

    auth_app.state.settings.public_origin = "https://qa.example"
    headers = {**csrf(client), "Origin": "https://qa.example"}
    assert client.post("/api/v1/auth/login", json={}, headers=headers).status_code == 422
    headers["Origin"] = "http://testserver"
    assert client.post("/api/v1/auth/login", json={}, headers=headers).status_code == 403
