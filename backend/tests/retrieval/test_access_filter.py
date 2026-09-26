import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, update

from app.modules.auth.schemas import Actor
from app.modules.ingestion.models import Chunk, Document, DocumentRevision
from app.modules.knowledge.models import FAQ, KnowledgeBase, KnowledgeMembership
from tests.retrieval import search_helpers
from tests.retrieval.search_helpers import FixedEmbedder
from tests.retrieval.test_semantic_search import search

search_data = search_helpers.search_data


def test_permissions_and_requested_scope_apply_before_limit(search_data):
    data = search_data
    authorized = data.kb()
    hidden = data.kb(member=False)
    unrequested = data.kb(visibility="public")
    expected = data.document(authorized, score=0.8)[2]
    for kb in [hidden, unrequested]:
        data.document(kb, score=1.0, text="不应泄漏")
    hits = search(data, [authorized, hidden], top_k=1)
    assert [hit.chunk_id for hit in hits] == [expected]


def test_empty_or_unauthorized_scope_never_calls_model(search_data):
    from app.modules.retrieval.service import RetrievalService

    data = search_data
    hidden = data.kb(member=False)
    data.document(hidden)

    def forbidden():
        pytest.fail("No authorized scope must not invoke the model")

    service = RetrievalService(data.factory, FixedEmbedder(forbidden))
    for ids in [[], [hidden], [uuid4()]]:
        assert asyncio.run(service.search(data.actor, ids, "开放时间")) == []


@pytest.mark.parametrize("action", ["revoke", "disable", "restrict"])
def test_reauthorizes_after_embedding(search_data, action):
    from app.modules.retrieval.service import RetrievalService

    data = search_data
    kb = data.kb(
        visibility="public" if action == "restrict" else "restricted", member=action != "restrict"
    )
    data.document(kb)

    def change_access():
        with data.factory() as db:
            if action == "revoke":
                db.execute(delete(KnowledgeMembership).where(KnowledgeMembership.kb_id == kb))
            else:
                db.execute(
                    update(KnowledgeBase)
                    .where(KnowledgeBase.id == kb)
                    .values(
                        **(
                            {"is_active": False}
                            if action == "disable"
                            else {"visibility": "restricted"}
                        )
                    )
                )
            db.commit()

    service = RetrievalService(data.factory, FixedEmbedder(change_access))
    assert asyncio.run(service.search(data.actor, [kb], "开放时间")) == []


@pytest.mark.parametrize("status", ["processing", "parsed", "failed"])
def test_new_candidate_does_not_hide_old_active_revision(search_data, status):
    data = search_data
    kb = data.kb()
    document, old_revision, old_chunk = data.document(kb)
    with data.factory() as db:
        revision = DocumentRevision(
            document_id=document,
            filename="new.txt",
            content_sha256=uuid4().hex * 2,
            storage_key=str(uuid4()),
            file_type="txt",
        )
        db.add(revision)
        db.flush()
        db.execute(
            update(Document)
            .where(Document.id == document)
            .values(candidate_revision_id=revision.id, status=status)
        )
        db.commit()
    assert [hit.chunk_id for hit in search(data, [kb])] == [old_chunk]
    with data.factory() as db:
        db.execute(
            update(Document)
            .where(Document.id == document)
            .values(active_revision_id=revision.id, status="ready")
        )
        db.commit()
    assert search(data, [kb]) == []


@pytest.mark.parametrize("status", ["disabled", "deleted"])
def test_disabled_or_deleted_document_is_excluded(search_data, status):
    kb = search_data.kb()
    search_data.document(kb, status=status)
    assert search(search_data, [kb]) == []


@pytest.mark.parametrize("changes", [{"active": False}, {"version": 2}, {"indexed_version": None}])
def test_faq_disabled_or_stale_index_is_excluded(search_data, changes):
    kb = search_data.kb()
    search_data.faq(kb, **changes)
    assert search(search_data, [kb]) == []


def test_faq_new_version_excludes_old_chunks_even_if_indexed(search_data):
    data = search_data
    kb = data.kb()
    faq, _ = data.faq(kb)
    with data.factory() as db:
        db.execute(update(FAQ).where(FAQ.id == faq).values(version=2, indexed_version=2))
        db.commit()
    assert search(data, [kb]) == []


def test_source_kb_mismatch_cannot_publish_restricted_content(search_data):
    data = search_data
    visible = data.kb()
    hidden = data.kb(member=False)
    document_chunk = data.document(hidden)[2]
    faq_chunk = data.faq(hidden)[1]
    with data.factory() as db:
        db.execute(
            update(Chunk).where(Chunk.id.in_([document_chunk, faq_chunk])).values(kb_id=visible)
        )
        db.commit()
    assert search(data, [visible]) == []


def test_hidden_or_inactive_model_mismatch_is_not_disclosed(search_data):
    data = search_data
    visible = data.kb()
    hidden = data.kb(member=False)
    disabled = data.kb(active=False)
    expected = data.document(visible)[2]
    bad = [
        data.document(hidden)[2],
        data.document(disabled)[2],
        data.document(visible, status="deleted")[2],
    ]
    with data.factory() as db:
        db.execute(update(Chunk).where(Chunk.id.in_(bad)).values(embedding_model="other"))
        db.commit()
    assert [hit.chunk_id for hit in search(data, [visible, hidden, disabled])] == [expected]


@pytest.mark.parametrize("role", ["user", "agent", "admin"])
def test_public_membership_and_admin_visibility_preserve_disabled_filter(search_data, role):
    from app.modules.retrieval.service import RetrievalService

    data = search_data
    public = data.kb(visibility="public", member=False)
    restricted = data.kb(member=False)
    disabled = data.kb(active=False)
    public_chunk = data.document(public)[2]
    restricted_chunk = data.document(restricted)[2]
    data.document(disabled)
    actor = Actor(user_id=data.actor.user_id, role=role)
    service = RetrievalService(data.factory, FixedEmbedder())
    hits = asyncio.run(service.search(actor, [public, restricted, disabled], "开放时间"))
    expected = [public_chunk, restricted_chunk] if role == "admin" else [public_chunk]
    assert {hit.chunk_id for hit in hits} == set(expected)


def test_revision_must_belong_to_its_document(search_data):
    data = search_data
    kb = data.kb()
    first_document, _, first_chunk = data.document(kb)
    _, foreign_revision, foreign_chunk = data.document(kb)
    with data.factory() as db:
        db.execute(
            update(Chunk)
            .where(Chunk.id == first_chunk)
            .values(revision_id=foreign_revision, chunk_index=1)
        )
        db.execute(
            update(Document)
            .where(Document.id == first_document)
            .values(active_revision_id=foreign_revision)
        )
        db.commit()
    assert [hit.chunk_id for hit in search(data, [kb])] == [foreign_chunk]


def test_inactive_candidate_vector_never_matches_or_reports_model_mismatch(search_data):
    data = search_data
    kb = data.kb()
    document, _, current_chunk = data.document(kb)
    with data.factory() as db:
        revision = DocumentRevision(
            document_id=document,
            filename="candidate.txt",
            content_sha256=uuid4().hex * 2,
            storage_key=str(uuid4()),
            file_type="txt",
        )
        db.add(revision)
        db.flush()
        db.add(
            Chunk(
                kb_id=kb,
                document_id=document,
                revision_id=revision.id,
                chunk_index=0,
                text="候选版本不可返回",
                title="候选",
                embedding=search_helpers.vector(),
                embedding_model="old-model",
                embedding_version="old-revision",
            )
        )
        db.execute(
            update(Document)
            .where(Document.id == document)
            .values(status="parsed", candidate_revision_id=revision.id)
        )
        db.commit()
    assert [hit.chunk_id for hit in search(data, [kb])] == [current_chunk]
