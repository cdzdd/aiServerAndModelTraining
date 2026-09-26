from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.models import AuditEvent
from tests.auth.conftest import csrf


@pytest.mark.parametrize("comment", [" ", "a" * 2001, "bad\0text", "\ud800", None, 4])
def test_feedback_rejects_invalid_comment(comment):
    from app.modules.feedback.schemas import FeedbackCreate

    with pytest.raises(ValidationError):
        FeedbackCreate(rating="down", comment=comment)


def test_feedback_defaults_and_partial_update_contract():
    from app.modules.feedback.schemas import FeedbackCreate, FeedbackPatch, ResolutionInput

    assert FeedbackCreate(rating="up").comment == ""
    assert FeedbackCreate(rating="down", comment="  错误原因  ").comment == "错误原因"
    for payload in [{}, {"comment": None}, {"status": "resolved"}]:
        with pytest.raises(ValidationError):
            FeedbackPatch(**payload)
    for payload in [{"status": "resolved"}, {"status": "open", "resolution": "说明"}]:
        with pytest.raises(ValidationError):
            ResolutionInput(**payload)


def test_submit_read_idempotency_and_conflicting_post(client, reply, auth_app):
    from app.modules.feedback.models import Feedback

    path = f"/api/v1/messages/{reply['id']}/feedback"
    assert client.get(path).json() is None
    first = client.post(
        path, json={"rating": "down", "comment": "  有错误  "}, headers=csrf(client)
    )
    assert first.status_code == 201
    value = first.json()
    assert value["comment"] == "有错误" and value["status"] == "open"
    assert "source_versions" not in value
    assert client.get(path).json() == value
    duplicate = client.post(
        path, json={"rating": "down", "comment": "有错误"}, headers=csrf(client)
    )
    assert duplicate.status_code == 200 and duplicate.json() == value
    assert client.post(path, json={"rating": "up"}, headers=csrf(client)).status_code == 409
    with auth_app.state.session_factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Feedback)
                .where(Feedback.message_id == UUID(reply["id"]))
            )
            == 1
        )
        audits = db.scalars(select(AuditEvent).where(AuditEvent.target_id == value["id"])).all()
        assert [event.action for event in audits] == ["feedback.create"]
        assert "有错误" not in str([event.event_metadata for event in audits])


def test_simultaneous_identical_posts_create_one_row_and_one_audit(client, reply, auth_app):
    from app.modules.feedback.models import Feedback

    headers = csrf(client)

    def send(_):
        return client.post(
            f"/api/v1/messages/{reply['id']}/feedback", json={"rating": "up"}, headers=headers
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, range(2)))
    assert sorted(response.status_code for response in responses) == [200, 201]
    assert len({response.json()["id"] for response in responses}) == 1
    with auth_app.state.session_factory() as db:
        feedback = db.scalar(select(Feedback).where(Feedback.message_id == UUID(reply["id"])))
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.target_id == str(feedback.id), AuditEvent.action == "feedback.create"
                )
            )
            == 1
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"rating": "other"},
        {"rating": True},
        {"rating": "up", "user_id": "forged"},
        {"rating": "up", "source_versions": []},
        {"rating": "up", "comment": " "},
        {"rating": "up", "comment": None},
        {"rating": "up", "comment": "x" * 2001},
        {"rating": "up", "comment": "bad\0"},
    ],
)
def test_http_rejects_forged_and_invalid_input(client, reply, payload):
    response = client.post(
        f"/api/v1/messages/{reply['id']}/feedback", json=payload, headers=csrf(client)
    )
    assert response.status_code == 422
