from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

PASSWORD = "a-test-password-123"


@pytest.fixture
def auth_app(migrated_engine, tmp_path):
    from app.core.config import Settings
    from app.main import create_app

    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL=migrated_engine.url.render_as_string(hide_password=False),
        SESSION_SECRET="test-auth-secret-at-least-32-characters",
        UPLOAD_DIR=tmp_path,
    )
    app = create_app(settings)
    app.state.auth_clock = lambda: datetime.now(UTC)
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(auth_app):
    with TestClient(auth_app, base_url="http://testserver") as client:
        yield client


def csrf(client):
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return {
        "X-CSRF-Token": response.json()["csrf_token"],
        "Origin": str(client.base_url).rstrip("/"),
    }


def register(client, username=None, **extra):
    body = {
        "username": username or f"user-{uuid4().hex[:12]}",
        "password": PASSWORD,
        "display_name": "测试用户",
        **extra,
    }
    return client.post("/api/v1/auth/register", json=body, headers=csrf(client))


def login(client, username, password=PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers=csrf(client),
    )


@pytest.fixture
def user(client):
    response = register(client)
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def signed_in(client, user):
    response = login(client, user["username"])
    assert response.status_code == 200
    return user


@pytest.fixture
def admin(client, user, migrated_engine):
    with migrated_engine.begin() as db:
        db.execute(text("UPDATE users SET role='admin' WHERE id=:id"), {"id": user["id"]})
    assert login(client, user["username"]).status_code == 200
    yield {**user, "role": "admin"}
    # Each test owns only its explicitly created admin; don't contaminate later last-admin tests.
    with migrated_engine.begin() as db:
        db.execute(text("UPDATE users SET role='user' WHERE id=:id"), {"id": user["id"]})
