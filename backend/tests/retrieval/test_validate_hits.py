import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, update

from app.modules.ingestion.models import Chunk, Document, DocumentRevision
from app.modules.knowledge.models import FAQ, KnowledgeBase, KnowledgeMembership
from app.modules.retrieval.service import RetrievalService
from tests.retrieval import search_helpers
from tests.retrieval.search_helpers import FixedEmbedder
from tests.retrieval.test_semantic_search import search

search_data = search_helpers.search_data


def validate(data, ids, hits):
    def forbidden():
        pytest.fail("Source validation must not invoke embedding")

    return asyncio.run(
        RetrievalService(data.factory, FixedEmbedder(forbidden)).validate_hits(
            data.actor, ids, hits
        )
    )


def test_current_document_and_faq_validate_with_no_embedding(search_data):
    data = search_data
    kb = data.kb()
    data.document(kb)
    data.faq(kb)
    hits = search(data, [kb])
    assert validate(data, [kb], hits) is True
    assert validate(data, [kb], hits[1:]) is True
    assert validate(data, [kb], []) is False
    assert validate(data, [], hits) is False
    assert validate(data, [uuid4()], hits) is False


@pytest.mark.parametrize("action", ["revoke", "restrict", "disable"])
def test_committed_permission_changes_invalidate_previously_retrieved_hits(search_data, action):
    data = search_data
    kb = data.kb(
        visibility="public" if action == "restrict" else "restricted", member=action != "restrict"
    )
    data.document(kb)
    hits = search(data, [kb])
    assert validate(data, [kb], hits)
    with data.factory() as db:
        if action == "revoke":
            db.execute(delete(KnowledgeMembership).where(KnowledgeMembership.kb_id == kb))
        else:
            db.execute(
                update(KnowledgeBase)
                .where(KnowledgeBase.id == kb)
                .values(
                    **(
                        {"visibility": "restricted"}
                        if action == "restrict"
                        else {"is_active": False}
                    )
                )
            )
        db.commit()
    assert validate(data, [kb], hits) is False


@pytest.mark.parametrize("action", ["deleted", "disabled", "switch_revision"])
def test_document_changes_invalidate_original_revision(search_data, action):
    data = search_data
    kb = data.kb()
    document, _, _ = data.document(kb)
    hits = search(data, [kb])
    with data.factory() as db:
        if action == "switch_revision":
            revision = DocumentRevision(
                document_id=document,
                filename="new.txt",
                content_sha256=uuid4().hex * 2,
                storage_key=str(uuid4()),
                file_type="txt",
            )
            db.add(revision)
            db.flush()
            changes = {"active_revision_id": revision.id}
        else:
            changes = {"status": action}
        db.execute(update(Document).where(Document.id == document).values(**changes))
        db.commit()
    assert validate(data, [kb], hits) is False


@pytest.mark.parametrize(
    "changes",
    [
        {"is_active": False},
        {"version": 2},
        {"version": 2, "indexed_version": 2},
        {"indexed_version": None},
    ],
)
def test_faq_version_and_active_changes_invalidate_original_hit(search_data, changes):
    data = search_data
    kb = data.kb()
    faq, _ = data.faq(kb)
    hits = search(data, [kb])
    with data.factory() as db:
        db.execute(update(FAQ).where(FAQ.id == faq).values(**changes))
        db.commit()
    assert validate(data, [kb], hits) is False


@pytest.mark.parametrize(
    "changes",
    [
        {"text": "已改原文"},
        {"title": "已改标题"},
        {"line_number": 9},
        {"page_number": 3},
        {"paragraph_number": 2},
        {"embedding_model": "other-model"},
        {"embedding_version": "other-version"},
        {"embedding": None},
    ],
)
def test_same_chunk_uuid_cannot_hide_text_location_or_embedding_changes(search_data, changes):
    data = search_data
    kb = data.kb()
    _, _, chunk = data.document(kb)
    hits = search(data, [kb])
    with data.factory() as db:
        db.execute(update(Chunk).where(Chunk.id == chunk).values(**changes))
        db.commit()
    assert validate(data, [kb], hits) is False


@pytest.mark.parametrize(
    "changes",
    [
        {"chunk_id": uuid4()},
        {"kb_id": uuid4()},
        {"source_id": uuid4()},
        {"revision_id": uuid4()},
        {"faq_version": 7},
        {"source_type": "faq"},
        {"text": "伪造文本"},
        {"title": "伪造标题"},
    ],
)
def test_exact_snapshot_is_required_even_with_a_real_chunk_id(search_data, changes):
    data = search_data
    kb = data.kb()
    data.document(kb)
    hits = search(data, [kb])
    assert validate(data, [kb], [hits[0].model_copy(update=changes)]) is False


def test_mixed_valid_and_invalid_sources_fail_as_a_whole(search_data):
    data = search_data
    kb = data.kb()
    data.document(kb)
    faq, _ = data.faq(kb)
    hits = search(data, [kb])
    with data.factory() as db:
        db.execute(update(FAQ).where(FAQ.id == faq).values(is_active=False))
        db.commit()
    assert validate(data, [kb], hits) is False


def test_new_candidate_preserves_still_active_document(search_data):
    data = search_data
    kb = data.kb()
    document, _, _ = data.document(kb)
    hits = search(data, [kb])
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
        db.execute(
            update(Document)
            .where(Document.id == document)
            .values(
                candidate_revision_id=revision.id,
                status="processing",
            )
        )
        db.commit()
    assert validate(data, [kb], hits) is True


def test_source_kb_integrity_is_rechecked_from_database(search_data):
    data = search_data
    kb = data.kb()
    hidden = data.kb(member=False)
    document, _, _ = data.document(kb)
    hits = search(data, [kb])
    with data.factory() as db:
        db.execute(update(Document).where(Document.id == document).values(kb_id=hidden))
        db.commit()
    assert validate(data, [kb], hits) is False


def test_external_committed_revocation_is_seen_by_new_validation_session(migrated_engine):
    from sqlalchemy.orm import sessionmaker

    from tests.retrieval.search_helpers import SearchData

    # Separate connections (not savepoints) model revocation during an external model call.
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    data = SearchData(factory)
    kb = data.kb()
    data.document(kb)
    hits = search(data, [kb])
    assert validate(data, [kb], hits) is True
    with migrated_engine.begin() as connection:
        connection.execute(delete(KnowledgeMembership).where(KnowledgeMembership.kb_id == kb))
    assert validate(data, [kb], hits) is False
