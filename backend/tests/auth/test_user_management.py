from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from .conftest import csrf, login, register


def test_admin_list_paginated_and_private(client, admin):
    response = client.get("/api/v1/admin/users?page=1&page_size=1")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1 and body["total"] >= 1
    assert body["page"] == 1 and body["page_size"] == 1
    assert "password" not in response.text and "token" not in response.text
    assert client.get("/api/v1/admin/users?page_size=101").status_code == 422


@pytest.mark.parametrize("patch", [{"role": "user"}, {"role": "agent"}, {"is_active": False}])
def test_last_active_admin_protected(client, admin, patch):
    response = client.patch(f"/api/v1/admin/users/{admin['id']}", json=patch, headers=csrf(client))
    assert response.status_code == 409
    assert client.get("/api/v1/auth/me").json()["role"] == "admin"


def test_disable_reenable_does_not_restore_old_session(client, admin, auth_app, migrated_engine):
    with TestClient(auth_app) as other:
        target = register(other).json()
        assert login(other, target["username"]).status_code == 200
        for active in (False, True):
            response = client.patch(
                f"/api/v1/admin/users/{target['id']}",
                json={"is_active": active},
                headers=csrf(client),
            )
            assert response.status_code == 200
            assert other.get("/api/v1/auth/me").status_code == 401
    with migrated_engine.connect() as db:
        events = (
            db.execute(
                text(
                    "SELECT metadata FROM audit_events WHERE action='user.update' AND target_id=:id"
                ),
                {"id": target["id"]},
            )
            .scalars()
            .all()
        )
    assert len(events) == 2
    assert "password" not in str(events)


def test_role_changes_apply_to_existing_session(client, admin, auth_app):
    with TestClient(auth_app) as other:
        target = register(other).json()
        login(other, target["username"])
        response = client.patch(
            f"/api/v1/admin/users/{target['id']}",
            json={"role": "admin", "display_name": "新管理员"},
            headers=csrf(client),
        )
        assert response.status_code == 200 and response.json()["display_name"] == "新管理员"
        assert other.get("/api/v1/admin/users").status_code == 200
        assert (
            client.patch(
                f"/api/v1/admin/users/{target['id']}", json={"role": "user"}, headers=csrf(client)
            ).status_code
            == 200
        )
        assert other.get("/api/v1/admin/users").status_code == 403


@pytest.mark.parametrize(
    "patch",
    [
        {"role": "owner"},
        {"is_active": None},
        {"role": None},
        {"display_name": " "},
        {"password": "changed-password"},
        {"is_active": "false"},
        {},
    ],
)
def test_invalid_user_patch_rejected(client, admin, patch):
    assert (
        client.patch(
            f"/api/v1/admin/users/{admin['id']}", json=patch, headers=csrf(client)
        ).status_code
        == 422
    )


def test_missing_user_404(client, admin):
    assert (
        client.patch(
            f"/api/v1/admin/users/{uuid4()}", json={"display_name": "name"}, headers=csrf(client)
        ).status_code
        == 404
    )


def test_non_admin_cannot_write_users(client, signed_in):
    assert (
        client.patch(
            f"/api/v1/admin/users/{signed_in['id']}", json={"role": "admin"}, headers=csrf(client)
        ).status_code
        == 403
    )
    assert client.get("/api/v1/auth/me").json()["role"] == "user"


def test_concurrent_self_demotion_keeps_an_active_admin(client, admin, auth_app, migrated_engine):
    with TestClient(auth_app) as other:
        second = register(other).json()
        assert (
            client.patch(
                f"/api/v1/admin/users/{second['id']}", json={"role": "admin"}, headers=csrf(client)
            ).status_code
            == 200
        )
        login(other, second["username"])
        headers1, headers2 = csrf(client), csrf(other)

        def demote(c, user, headers):
            return c.patch(
                f"/api/v1/admin/users/{user['id']}", json={"role": "user"}, headers=headers
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(demote, client, admin, headers1)
            b = pool.submit(demote, other, second, headers2)
            assert sorted([a.result(), b.result()]) == [200, 409]
    with migrated_engine.connect() as db:
        assert (
            db.execute(text("SELECT count(*) FROM users WHERE role='admin' AND is_active")).scalar()
            == 1
        )
