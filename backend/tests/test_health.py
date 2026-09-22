import json
import logging
import socket
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient


def make_settings(tmp_path, database_url):
    from app.core.config import Settings

    return Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL=database_url,
        SESSION_SECRET="test-only-session-secret",
        UPLOAD_DIR=tmp_path,
    )


def test_missing_configuration_names_fields_without_exposing_secrets(monkeypatch):
    from app.core.config import Settings

    for name in ("APP_ENV", "DATABASE_URL", "SESSION_SECRET", "UPLOAD_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SESSION_SECRET", "do-not-print-this-test-secret")
    with pytest.raises(ValueError) as error:
        Settings(_env_file=None)
    message = str(error.value)
    assert "DATABASE_URL" in message
    assert "UPLOAD_DIR" in message
    assert "do-not-print-this-test-secret" not in message


def test_liveness_does_not_require_a_database_connection(tmp_path):
    from app.main import create_app

    settings = make_settings(tmp_path, "postgresql+psycopg://unused:unused@127.0.0.1:1/test")
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert UUID(response.headers["X-Request-ID"])


def test_readiness_failure_is_safe_and_correlated(tmp_path, caplog):
    from app.main import create_app

    # A bound, non-listening local socket refuses connections without a live DB dependency.
    with socket.socket() as blocked_port:
        blocked_port.bind(("127.0.0.1", 0))
        port = blocked_port.getsockname()[1]
        settings = make_settings(
            tmp_path,
            f"postgresql+psycopg://test:never-leak-database-password@127.0.0.1:{port}/test",
        )
        request_id = str(uuid4())
        with caplog.at_level(logging.INFO, logger="app.requests"):
            with TestClient(create_app(settings)) as client:
                response = client.get("/health/ready", headers={"X-Request-ID": request_id})
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "DEPENDENCY_UNAVAILABLE"
    assert error["request_id"] == request_id == response.headers["X-Request-ID"]
    assert "never-leak-database-password" not in response.text + caplog.text
    assert "test-only-session-secret" not in response.text + caplog.text
    events = [
        json.loads(record.message) for record in caplog.records if record.name == "app.requests"
    ]
    assert any(
        event["request_id"] == request_id and event["status_code"] == 503 for event in events
    )


def test_invalid_request_id_is_replaced(tmp_path):
    from app.main import create_app

    settings = make_settings(tmp_path, "postgresql+psycopg://unused:unused@127.0.0.1:1/test")
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/live", headers={"X-Request-ID": "invalid untrusted value"})
    assert UUID(response.headers["X-Request-ID"])
    assert response.headers["X-Request-ID"] != "invalid untrusted value"


def test_readiness_checks_a_real_database(migrated_engine, tmp_path):
    from app.main import create_app

    settings = make_settings(tmp_path, migrated_engine.url.render_as_string(hide_password=False))
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.parametrize(
    "overrides, field_name",
    [
        ({"DATABASE_URL": "invalid://user:private-password@host/db"}, "DATABASE_URL"),
        ({"SESSION_SECRET": ""}, "SESSION_SECRET"),
        ({"UPLOAD_DIR": ""}, "UPLOAD_DIR"),
    ],
)
def test_invalid_required_configuration_fails_safely(tmp_path, overrides, field_name):
    from app.core.config import Settings

    values = {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+psycopg://test:private-password@localhost/test",
        "SESSION_SECRET": "private-session-secret",
        "UPLOAD_DIR": str(tmp_path),
    }
    values.update(overrides)
    with pytest.raises(ValueError) as error:
        Settings(_env_file=None, **values)
    assert field_name in str(error.value)
    assert "private-password" not in str(error.value)
    assert "private-session-secret" not in str(error.value)


def test_environment_file_loads_backend_values_among_shared_worktree_settings(
    tmp_path, monkeypatch
):
    from app.core.config import Settings

    for name in ("APP_ENV", "DATABASE_URL", "SESSION_SECRET", "UPLOAD_DIR"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=test\n"
        "DATABASE_URL=postgresql+psycopg://test:hidden-password@localhost/test\n"
        "SESSION_SECRET=hidden-session-secret\n"
        "UPLOAD_DIR=.local/uploads\n"
        "COMPOSE_PROJECT_NAME=isolated-test\n"
        "WEB_PORT=5201\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=env_file)
    assert settings.app_env == "test"
    assert settings.upload_dir.is_absolute()
    assert "hidden-password" not in repr(settings)
    assert "hidden-session-secret" not in repr(settings)


def test_unknown_routes_use_safe_standard_error_envelope(tmp_path, caplog):
    from app.main import create_app

    settings = make_settings(tmp_path, "postgresql+psycopg://unused:unused@127.0.0.1:1/test")
    with caplog.at_level(logging.INFO, logger="app.requests"):
        with TestClient(create_app(settings)) as client:
            response = client.get("/private-token-route?secret=private-query")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "private-token-route" not in caplog.text
    assert "private-query" not in caplog.text


def test_unexpected_failures_hide_exception_details_and_keep_request_id(tmp_path, caplog):
    from app.main import create_app

    settings = make_settings(tmp_path, "postgresql+psycopg://unused:unused@127.0.0.1:1/test")
    app = create_app(settings)

    @app.get("/test-failure")
    def fail():
        raise RuntimeError("do-not-disclose-internal-password")

    with caplog.at_level(logging.INFO, logger="app.requests"):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/test-failure")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "do-not-disclose-internal-password" not in response.text + caplog.text


def test_validation_errors_omit_raw_input_and_use_standard_details(tmp_path):
    from app.main import create_app

    settings = make_settings(tmp_path, "postgresql+psycopg://unused:unused@127.0.0.1:1/test")
    app = create_app(settings)

    @app.get("/test-input")
    def input_route(count: int):
        return {"count": count}

    with TestClient(app) as client:
        response = client.get("/test-input", params={"count": "private-invalid-input"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert error["details"]
    assert "private-invalid-input" not in response.text


def test_method_not_allowed_preserves_protocol_headers(tmp_path):
    from app.main import create_app

    settings = make_settings(tmp_path, "postgresql+psycopg://unused:unused@127.0.0.1:1/test")
    with TestClient(create_app(settings)) as client:
        response = client.post("/health/live")
    assert response.status_code == 405
    assert "GET" in response.headers["Allow"]
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
