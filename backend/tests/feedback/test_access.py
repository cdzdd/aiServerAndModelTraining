from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.modules.auth.models import User
from app.modules.chat.models import Conversation, Message
from tests.auth.conftest import csrf, login, register


@pytest.mark.parametrize(
    "role,status",
    [
        ("assistant", "generating"),
        ("assistant", "failed"),
        ("assistant", "cancelled"),
        ("user", "complete"),
        ("agent", "complete"),
        ("system", "complete"),
    ],
)
def test_ineligible_messages_rejected_for_read_and_write(client, reply, auth_app, role, status):
    with auth_app.state.session_factory() as db:
        db.execute(
            update(Message).where(Message.id == UUID(reply["id"])).values(role=role, status=status)
        )
        db.commit()
    path = f"/api/v1/messages/{reply['id']}/feedback"
    assert client.get(path).status_code == 409
    assert client.post(path, json={"rating": "up"}, headers=csrf(client)).status_code == 409


@pytest.mark.parametrize("role", ["user", "agent", "admin"])
def test_other_owner_even_admin_or_assignee_cannot_rate_or_read_own_endpoint(
    client, reply, auth_app, role
):
    created = client.post(
        f"/api/v1/messages/{reply['id']}/feedback", json={"rating": "up"}, headers=csrf(client)
    )
    assert created.status_code == 201
    with TestClient(auth_app) as other:
        person = register(other).json()
        with auth_app.state.session_factory() as db:
            db.execute(update(User).where(User.id == UUID(person["id"])).values(role=role))
            db.execute(
                update(Conversation)
                .where(Conversation.id == UUID(reply["conversation_id"]))
                .values(assigned_agent_id=UUID(person["id"]), mode="human")
            )
            db.commit()
        assert login(other, person["username"]).status_code == 200
        path = f"/api/v1/messages/{reply['id']}/feedback"
        assert other.get(path).status_code == 404
        assert other.post(path, json={"rating": "down"}, headers=csrf(other)).status_code == 404
        assert (
            other.patch(
                f"/api/v1/feedback/{created.json()['id']}",
                json={"rating": "down"},
                headers=csrf(other),
            ).status_code
            == 404
        )


def test_deleted_conversation_denies_owner_endpoints(client, reply, auth_app):
    created = client.post(
        f"/api/v1/messages/{reply['id']}/feedback", json={"rating": "up"}, headers=csrf(client)
    )
    assert created.status_code == 201
    with auth_app.state.session_factory() as db:
        db.execute(
            update(Conversation)
            .where(Conversation.id == UUID(reply["conversation_id"]))
            .values(deleted_at=datetime.now(UTC))
        )
        db.commit()
    path = f"/api/v1/messages/{reply['id']}/feedback"
    assert client.get(path).status_code == 404
    assert client.post(path, json={"rating": "up"}, headers=csrf(client)).status_code == 404
    assert (
        client.patch(
            f"/api/v1/feedback/{created.json()['id']}",
            json={"rating": "down"},
            headers=csrf(client),
        ).status_code
        == 404
    )


def test_closed_conversation_allows_feedback_and_writes_require_csrf(client, reply, auth_app):
    with auth_app.state.session_factory() as db:
        db.execute(
            update(Conversation)
            .where(Conversation.id == UUID(reply["conversation_id"]))
            .values(mode="closed")
        )
        db.commit()
    path = f"/api/v1/messages/{reply['id']}/feedback"
    assert client.post(path, json={"rating": "up"}).status_code == 403
    assert (
        client.post(
            path, json={"rating": "up"}, headers={**csrf(client), "Origin": "https://other.invalid"}
        ).status_code
        == 403
    )
    assert client.post(path, json={"rating": "up"}, headers=csrf(client)).status_code == 201
    with TestClient(auth_app) as anonymous:
        assert anonymous.get(path).status_code == 401


@pytest.mark.parametrize("role", ["user", "agent"])
def test_nonadmin_cannot_list_detail_or_process(client, reply, auth_app, signed_in, role):
    feedback = client.post(
        f"/api/v1/messages/{reply['id']}/feedback", json={"rating": "up"}, headers=csrf(client)
    ).json()
    with auth_app.state.session_factory() as db:
        db.execute(update(User).where(User.id == UUID(signed_in["id"])).values(role=role))
        db.commit()
    path = f"/api/v1/admin/feedback/{feedback['id']}"
    assert client.get("/api/v1/admin/feedback").status_code == 403
    assert client.get(path).status_code == 403
    assert (
        client.patch(
            path, json={"status": "resolved", "resolution": "test"}, headers=csrf(client)
        ).status_code
        == 403
    )


@pytest.mark.parametrize("role", ["agent", "admin"])
def test_active_owner_of_any_role_can_rate_own_reply(client, reply, signed_in, auth_app, role):
    from app.modules.auth.models import User

    with auth_app.state.session_factory() as db:
        db.execute(update(User).where(User.id == UUID(signed_in["id"])).values(role=role))
        db.commit()
    response = client.post(
        f"/api/v1/messages/{reply['id']}/feedback", json={"rating": "up"}, headers=csrf(client)
    )
    assert response.status_code == 201
    assert response.json()["user_id"] == signed_in["id"]
