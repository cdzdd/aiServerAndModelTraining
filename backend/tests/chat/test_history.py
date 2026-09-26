from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, update

from app.modules.chat.models import Message
from app.modules.ingestion.models import Chunk, Document
from app.modules.knowledge.models import FAQ, KnowledgeBase, KnowledgeMembership
from tests.chat import data_helpers

chat_data = data_helpers.chat_data


def quoted(data, *, faq=False):
    kb = data.kb()
    if faq:
        source, chunk_id = data.faq(kb)
    else:
        source, _, chunk_id = data.document(kb, text="图书馆九点开放。")
    conversation = data.conversation(kb_ids=[kb])
    reservation = data.reserve(conversation)
    with data.factory() as db:
        chunk = db.get(Chunk, chunk_id)
        citation = {
            "index": 1,
            "chunk_id": str(chunk.id),
            "kb_id": str(kb),
            "source_type": "faq" if faq else "document",
            "source_id": str(source),
            "title": chunk.title,
            "quote": chunk.text,
            "revision_id": str(chunk.revision_id) if chunk.revision_id else None,
            "faq_version": chunk.faq_version,
            "page_number": chunk.page_number,
            "paragraph_number": chunk.paragraph_number,
            "line_number": chunk.line_number,
        }
    data.finish(reservation, content=citation["quote"], citations=[citation])
    return conversation, reservation, citation


@pytest.mark.parametrize(
    "change", ["revoke", "disable_kb", "disable_doc", "delete_doc", "revision", "text", "quote"]
)
def test_history_projection_and_rag_pairs_drop_inaccessible_evidence_without_rewriting_db(
    chat_data, change
):
    from app.modules.chat.service import list_messages

    data = chat_data
    conversation, reservation, citation = quoted(data)
    with data.factory() as db:
        assert list_messages(db, data.actor, conversation.id)["items"][1].evidence_hidden is False
        kb = UUID(citation["kb_id"])
        if change == "revoke":
            db.execute(delete(KnowledgeMembership).where(KnowledgeMembership.kb_id == kb))
        elif change == "disable_kb":
            db.execute(update(KnowledgeBase).where(KnowledgeBase.id == kb).values(is_active=False))
        elif change in ["disable_doc", "delete_doc", "revision"]:
            values = (
                {"active_revision_id": uuid4()}
                if change == "revision"
                else {"status": "disabled" if change == "disable_doc" else "deleted"}
            )
            db.execute(
                update(Document).where(Document.id == UUID(citation["source_id"])).values(**values)
            )
        elif change == "text":
            db.execute(
                update(Chunk).where(Chunk.id == UUID(citation["chunk_id"])).values(text="新规定")
            )
        else:
            db.get(Message, reservation.assistant_message_id).citations = [
                citation | {"quote": "伪造"}
            ]
        db.commit()
    with data.factory() as db:
        views = list_messages(db, data.actor, conversation.id)["items"]
        assert views[0].content == "开放时间？"
        assert views[1].evidence_hidden is True
        assert views[1].content == "该回答所依据的资料当前不可访问"
        assert views[1].citations == []
        assert db.get(Message, reservation.assistant_message_id).content == citation["quote"]
    assert data.reserve(conversation).history == []


@pytest.mark.parametrize("changes", [{"version": 2}, {"is_active": False}])
def test_faq_citation_version_and_active_status_are_rechecked(chat_data, changes):
    from app.modules.chat.service import list_messages

    data = chat_data
    conversation, reservation, citation = quoted(data, faq=True)
    with data.factory() as db:
        db.execute(update(FAQ).where(FAQ.id == UUID(citation["source_id"])).values(**changes))
        db.commit()
    with data.factory() as db:
        assert list_messages(db, data.actor, conversation.id)["items"][1].evidence_hidden


def test_history_pagination_is_stable_and_rag_only_contains_last_three_complete_pairs(chat_data):
    from app.modules.chat.service import list_messages

    data = chat_data
    conversation = data.conversation()
    for index in range(5):
        reservation = data.reserve(conversation)
        data.finish(reservation, content=f"回答{index}")
    failed = data.reserve(conversation)
    data.finish(failed, status="failed", content="不得进入历史")
    next_reservation = data.reserve(conversation)
    assert [message.role for message in next_reservation.history] == ["user", "assistant"] * 3
    assert [
        message.content for message in next_reservation.history if message.role == "assistant"
    ] == ["回答2", "回答3", "回答4"]
    with data.factory() as db:
        page1 = list_messages(db, data.actor, conversation.id, page=1, page_size=3)
        page2 = list_messages(db, data.actor, conversation.id, page=2, page_size=3)
        assert len({view.id for view in page1["items"] + page2["items"]}) == 6
        assert [view.role for view in page1["items"]] == ["user", "assistant", "user"]
        assert page1["total"] == 14


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", str(uuid4())),
        ("kb_id", str(uuid4())),
        ("revision_id", str(uuid4())),
        ("source_type", "faq"),
        ("line_number", 999),
    ],
)
def test_history_citation_must_match_exact_chunk_source_and_locator(chat_data, field, value):
    from app.modules.chat.service import list_messages

    data = chat_data
    conversation, reservation, citation = quoted(data)
    with data.factory() as db:
        db.get(Message, reservation.assistant_message_id).citations = [citation | {field: value}]
        db.commit()
    with data.factory() as db:
        view = list_messages(db, data.actor, conversation.id)["items"][1]
        assert view.evidence_hidden and view.citations == []


def test_public_to_private_source_hides_history_without_membership(chat_data):
    from app.modules.chat.service import list_messages

    data = chat_data
    conversation, reservation, citation = quoted(data)
    kb = UUID(citation["kb_id"])
    with data.factory() as db:
        db.execute(delete(KnowledgeMembership).where(KnowledgeMembership.kb_id == kb))
        db.execute(update(KnowledgeBase).where(KnowledgeBase.id == kb).values(visibility="public"))
        db.commit()
    with data.factory() as db:
        assert not list_messages(db, data.actor, conversation.id)["items"][1].evidence_hidden
        db.execute(
            update(KnowledgeBase).where(KnowledgeBase.id == kb).values(visibility="restricted")
        )
        db.commit()
    with data.factory() as db:
        assert list_messages(db, data.actor, conversation.id)["items"][1].evidence_hidden


@pytest.mark.parametrize("change", [{"role": "user"}, {"is_active": False}])
def test_history_source_query_rechecks_role_changed_after_initial_identity_check(
    migrated_engine, monkeypatch, change
):
    from sqlalchemy.orm import sessionmaker

    from app.modules.auth.models import User
    from app.modules.chat import service

    data = data_helpers.ChatData(sessionmaker(bind=migrated_engine, expire_on_commit=False))
    conversation, reservation, citation = quoted(data)
    admin = data.person("admin")
    original = service.active_candidates

    def demote_before_query(actor, kb_ids):
        # Simulates an independent admin edit between the preliminary identity read and
        # the source SELECT. Keep the actual authorization/candidate SQL under test.
        with migrated_engine.begin() as changed:
            changed.execute(update(User).where(User.id == admin.user_id).values(**change))
        return original(actor, kb_ids)

    monkeypatch.setattr(service, "active_candidates", demote_before_query)
    with data.factory() as db:
        view = service.list_messages(db, admin, conversation.id)["items"][1]
        assert view.evidence_hidden
        assert citation["quote"] not in view.content


def test_rag_history_considers_only_recent_three_completed_pairs_without_ancient_refill(chat_data):
    data = chat_data
    conversation, first, citation = quoted(data)
    for index in range(1, 5):
        latest = data.reserve(conversation)
        data.finish(latest, content=f"回答{index}")
    with data.factory() as db:
        db.get(Message, latest.assistant_message_id).citations = [citation]
        db.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id == UUID(citation["kb_id"]))
            .values(is_active=False)
        )
        db.commit()
    next_reservation = data.reserve(conversation)
    assert [
        message.content for message in next_reservation.history if message.role == "assistant"
    ] == ["回答2", "回答3"]
