import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .conftest import create_faq, create_kb, csrf, members


def test_faq_crud_versions_and_soft_delete(client, admin, reader):
    other, _ = reader
    kb = create_kb(client, visibility="public")
    faq = create_faq(client, kb, question="  虚构问题  ", answer="  虚构答案  ")
    assert faq["question"] == "虚构问题" and faq["answer"] == "虚构答案"
    assert faq["version"] == 1 and faq["indexed_version"] is None
    path = f"/api/v1/faqs/{faq['id']}"
    updated = client.patch(
        path, json={"answer": "更正答案", "expected_version": 1}, headers=csrf(client)
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["updated_at"] >= faq["updated_at"]
    assert (
        client.patch(
            path, json={"answer": "过期", "expected_version": 1}, headers=csrf(client)
        ).status_code
        == 409
    )
    assert client.delete(path, headers=csrf(client)).status_code == 204
    assert other.get(f"/api/v1/knowledge-bases/{kb['id']}/faqs").json()["items"] == []
    stored = client.get(f"/api/v1/knowledge-bases/{kb['id']}/faqs").json()["items"][0]
    assert stored["id"] == faq["id"] and stored["is_active"] is False and stored["version"] == 3
    assert (
        client.patch(
            path, json={"is_active": True, "expected_version": 3}, headers=csrf(client)
        ).status_code
        == 200
    )
    assert other.get(f"/api/v1/knowledge-bases/{kb['id']}/faqs").json()["items"][0]["version"] == 4


@pytest.mark.parametrize(
    "changes",
    [
        {"question": ""},
        {"question": "   "},
        {"answer": " "},
        {"question": "x" * 501},
        {"answer": "x" * 10001},
        {"answer": "\u0000"},
        {"question": "\ud800"},
        {"answer": None},
        {"is_active": "false"},
        {"kb_id": str(uuid4())},
        {"created_by": str(uuid4())},
        {"version": 77},
        {"indexed_version": 1},
    ],
)
def test_invalid_or_forged_faq_fields(client, admin, changes):
    kb = create_kb(client)
    response = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/faqs",
        content=json.dumps({"question": "问题", "answer": "答案", **changes}),
        headers={**csrf(client), "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert client.get(f"/api/v1/knowledge-bases/{kb['id']}/faqs").json()["total"] == 0


def test_cross_library_moves_and_empty_patches_rejected(client, admin):
    first, second = create_kb(client), create_kb(client)
    faq = create_faq(client, first)
    for patch in ({"kb_id": second["id"]}, {"answer": None}, {}, {"is_active": "false"}):
        assert (
            client.patch(
                f"/api/v1/faqs/{faq['id']}",
                json={"expected_version": 1, **patch},
                headers=csrf(client),
            ).status_code
            == 422
        )
    assert client.get(f"/api/v1/knowledge-bases/{second['id']}/faqs").json()["total"] == 0
    assert (
        client.get(f"/api/v1/knowledge-bases/{first['id']}/faqs").json()["items"][0]["version"] == 1
    )


def test_retrieval_query_excludes_stale_disabled_and_revoked_faqs(
    client, admin, reader, migrated_engine
):
    # This simulates only the version marker owned by 007; no vector index is claimed here.
    from app.modules.auth.schemas import Actor
    from app.modules.knowledge.service import effective_faqs

    other, person = reader
    kb = create_kb(client)
    faq = create_faq(client, kb)
    assert members(client, kb, [person["id"]]).status_code == 200
    actor = Actor(user_id=UUID(person["id"]), role="user")

    def ids(kbs=None):
        with Session(migrated_engine) as db:
            return [
                str(f.id)
                for f in db.scalars(
                    effective_faqs(actor, kbs if kbs is not None else [UUID(kb["id"])])
                )
            ]

    assert ids() == []
    with migrated_engine.begin() as db:
        db.execute(text("UPDATE faqs SET indexed_version=version WHERE id=:id"), {"id": faq["id"]})
    assert ids() == [faq["id"]]
    assert ids([]) == []
    assert (
        client.patch(
            f"/api/v1/faqs/{faq['id']}",
            json={"answer": "新版本", "expected_version": 1},
            headers=csrf(client),
        ).status_code
        == 200
    )
    assert ids() == []
    with migrated_engine.begin() as db:
        db.execute(text("UPDATE faqs SET indexed_version=version WHERE id=:id"), {"id": faq["id"]})
    assert ids() == [faq["id"]]
    assert members(client, {**kb, "version": 2}, []).status_code == 200
    assert ids() == []
    assert members(client, {**kb, "version": 3}, [person["id"]]).status_code == 200
    assert ids() == [faq["id"]]
    assert client.delete(f"/api/v1/faqs/{faq['id']}", headers=csrf(client)).status_code == 204
    assert ids() == []


def test_knowledge_and_faq_audits_are_transactional_and_do_not_store_content(
    client, admin, reader, migrated_engine
):
    from app.core.models import AuditEvent

    _, person = reader
    kb = create_kb(client)
    faq = create_faq(client, kb, question="敏感问题-不能记录", answer="敏感答案-不能记录")
    members(client, kb, [person["id"]])
    client.patch(
        f"/api/v1/knowledge-bases/{kb['id']}",
        json={"description": "changed", "expected_version": 2},
        headers=csrf(client),
    )
    client.patch(
        f"/api/v1/faqs/{faq['id']}",
        json={"answer": "更新秘密", "expected_version": 1},
        headers=csrf(client),
    )
    client.delete(f"/api/v1/faqs/{faq['id']}", headers=csrf(client))
    with Session(migrated_engine) as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.target_id.in_([kb["id"], faq["id"]]))
        ).all()
        assert {event.action for event in events} == {
            "knowledge.create",
            "knowledge.update",
            "knowledge.members",
            "faq.create",
            "faq.update",
            "faq.disable",
        }
        assert len(events) == 6
        assert all(str(event.actor_id) == admin["id"] and event.request_id for event in events)
        metadata = json.dumps([event.event_metadata for event in events], ensure_ascii=False)
        assert "敏感" not in metadata and "秘密" not in metadata
