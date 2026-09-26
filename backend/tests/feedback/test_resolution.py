from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select, update

from app.core.models import AuditEvent
from app.modules.chat.models import Conversation, Message
from app.modules.knowledge.models import KnowledgeBase
from tests.auth.conftest import csrf


def submit(client, reply, **extra):
    response = client.post(
        f"/api/v1/messages/{reply['id']}/feedback",
        json={"rating": "down", **extra},
        headers=csrf(client),
    )
    assert response.status_code == 201
    return response.json()


def test_resolution_noops_owner_edit_reopens_and_audit_omits_private_text(
    client, reply, admin_reader, auth_app
):
    admin, person = admin_reader
    feedback = submit(client, reply, comment="private-comment-sentinel")
    path = f"/api/v1/admin/feedback/{feedback['id']}"
    payload = {"status": "resolved", "resolution": "private-resolution-sentinel"}
    resolved = admin.patch(path, json=payload, headers=csrf(admin))
    assert resolved.status_code == 200
    value = resolved.json()
    assert value["resolved_by"] == person["id"] and value["resolved_at"]
    assert admin.patch(path, json=payload, headers=csrf(admin)).json() == value
    unchanged = client.patch(
        f"/api/v1/feedback/{feedback['id']}", json={"rating": "down"}, headers=csrf(client)
    )
    assert unchanged.json() == value
    changed = client.patch(
        f"/api/v1/feedback/{feedback['id']}", json={"comment": "补充信息"}, headers=csrf(client)
    ).json()
    assert changed["status"] == "open" and changed["resolution"] == ""
    assert changed["resolved_by"] is changed["resolved_at"] is None
    assert changed["created_at"] == feedback["created_at"]
    with auth_app.state.session_factory() as db:
        audits = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.target_id == feedback["id"])
            .order_by(AuditEvent.created_at)
        ).all()
        assert [row.action for row in audits] == [
            "feedback.create",
            "feedback.resolve",
            "feedback.update",
        ]
        assert "private-" not in str([row.event_metadata for row in audits])
        assert db.get(Message, UUID(reply["id"])).content == "测试回答"


def test_admin_reopen_clears_resolution_and_filtered_list_detail(client, reply, admin_reader):
    admin, _ = admin_reader
    feedback = submit(client, reply)
    path = f"/api/v1/admin/feedback/{feedback['id']}"
    assert (
        admin.patch(
            path, json={"status": "resolved", "resolution": "已核查"}, headers=csrf(admin)
        ).status_code
        == 200
    )
    response = admin.patch(path, json={"status": "open"}, headers=csrf(admin))
    assert response.status_code == 200
    assert response.json()["resolved_by"] is None
    listing = admin.get("/api/v1/admin/feedback?status=open&rating=down&page_size=100").json()
    assert feedback["id"] in {row["id"] for row in listing["items"]}
    detail = admin.get(path).json()
    assert detail["message_available"] is True
    assert detail["message"]["content"] == "测试回答"
    assert "source_versions" not in detail["feedback"]
    assert admin.get(path).headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "resolved"},
        {"status": "resolved", "resolution": " "},
        {"status": "resolved", "resolution": "x" * 2001},
        {"status": "open", "resolution": "cannot retain"},
        {"status": "resolved", "resolution": None},
        {"status": "other"},
        {"status": "open", "resolved_by": "forged"},
    ],
)
def test_admin_validation(client, reply, admin_reader, payload):
    admin, _ = admin_reader
    feedback = submit(client, reply)
    response = admin.patch(
        f"/api/v1/admin/feedback/{feedback['id']}", json=payload, headers=csrf(admin)
    )
    assert response.status_code == 422


def test_soft_delete_preserves_admin_feedback_but_not_original_message(
    client, reply, auth_app, admin_reader
):
    admin, _ = admin_reader
    feedback = submit(client, reply, comment="保留处理理由")
    with auth_app.state.session_factory() as db:
        db.execute(
            update(Conversation)
            .where(Conversation.id == UUID(reply["conversation_id"]))
            .values(deleted_at=datetime.now(UTC))
        )
        db.commit()
    detail = admin.get(f"/api/v1/admin/feedback/{feedback['id']}").json()
    assert detail["feedback"]["comment"] == "保留处理理由"
    assert detail["message_available"] is False and detail["message"] is None
    assert "测试回答" not in str(detail)


def test_source_snapshot_is_server_metadata_and_current_projection_hides_disabled_source(
    client, reply, auth_app, admin_reader
):
    from app.modules.feedback.models import Feedback
    from app.modules.ingestion.models import Chunk
    from tests.retrieval.search_helpers import SearchData

    admin, _ = admin_reader
    data = SearchData(auth_app.state.session_factory)
    doc_id, revision_id, chunk_id = data.document(
        UUID(reply["kb_id"]), text="source-quote-sentinel"
    )
    citation = {
        "index": 1,
        "chunk_id": str(chunk_id),
        "kb_id": reply["kb_id"],
        "source_type": "document",
        "source_id": str(doc_id),
        "revision_id": str(revision_id),
        "faq_version": None,
        "title": "服务",
        "quote": "source-quote-sentinel",
        "page_number": None,
        "paragraph_number": None,
        "line_number": 7,
    }
    with auth_app.state.session_factory() as db:
        message = db.get(Message, UUID(reply["id"]))
        message.content, message.citations = "source-quote-sentinel", [citation]
        db.commit()
    feedback = submit(client, reply)
    with auth_app.state.session_factory() as db:
        stored = db.get(Feedback, UUID(feedback["id"]))
        assert stored.source_versions == [
            {
                key: citation[key]
                for key in [
                    "chunk_id",
                    "kb_id",
                    "source_type",
                    "source_id",
                    "revision_id",
                    "faq_version",
                ]
            }
        ]
        assert db.get(Chunk, chunk_id).text == "source-quote-sentinel"
        db.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id == UUID(reply["kb_id"]))
            .values(is_active=False)
        )
        db.commit()
    detail = admin.get(f"/api/v1/admin/feedback/{feedback['id']}").json()
    assert detail["message"]["evidence_hidden"] is True
    assert detail["message"]["citations"] == []
    assert "source-quote-sentinel" not in str(detail)
