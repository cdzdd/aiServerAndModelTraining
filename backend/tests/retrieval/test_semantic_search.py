import asyncio
from uuid import UUID

import pytest
from sqlalchemy import update

from app.modules.ingestion.models import Chunk
from tests.retrieval import search_helpers
from tests.retrieval.search_helpers import FixedEmbedder

search_data = search_helpers.search_data


def search(data, kb_ids, **kwargs):
    from app.modules.retrieval.service import RetrievalService

    return asyncio.run(
        RetrievalService(data.factory, FixedEmbedder(), threshold=0.75).search(
            data.actor, kb_ids, "什么时候开放", **kwargs
        )
    )


def test_cosine_order_threshold_top_k_and_source_metadata(search_data):
    data = search_data
    kb = data.kb()
    _, revision, best = data.document(kb, score=1.0)
    faq_id, second = data.faq(kb, score=0.8)
    data.document(kb, score=0.7)
    hits = search(data, [kb])
    assert [hit.chunk_id for hit in hits] == [best, second]
    assert [hit.score for hit in hits] == pytest.approx([1.0, 0.8])
    assert hits[0].kb_id == kb
    assert hits[0].revision_id == revision
    assert hits[0].source_type == "document"
    assert hits[0].line_number == 7
    assert hits[0].text == "文档知识"
    assert hits[1].source_type == "faq"
    assert hits[1].source_id == faq_id
    assert hits[1].faq_version == 1
    assert [hit.chunk_id for hit in search(data, [kb], top_k=1)] == [best]


def test_exact_ties_use_stable_chunk_id_and_default_limit_five(search_data):
    data = search_data
    kb = data.kb()
    ids = [data.document(kb)[2] for _ in range(7)]
    assert [hit.chunk_id for hit in search(data, [kb])] == sorted(ids)[:5]


def test_threshold_boundary_and_no_match(search_data):
    data = search_data
    kb = data.kb()
    data.document(kb, score=0.5)
    assert search(data, [kb]) == []
    from app.modules.retrieval.service import RetrievalService

    service = RetrievalService(data.factory, FixedEmbedder(), threshold=0.5)
    assert len(asyncio.run(service.search(data.actor, [kb], "开放时间"))) == 1


@pytest.mark.parametrize("top_k", [0, 21, True, 1.5])
def test_top_k_rejects_out_of_range_and_nonintegers(search_data, top_k):
    from app.modules.retrieval.schemas import RetrievalError

    with pytest.raises(RetrievalError, match="INVALID_TOP_K"):
        search(search_data, [], top_k=top_k)


@pytest.mark.parametrize("query", ["", "  \n\t", "\0"])
def test_empty_or_invalid_query_is_rejected_without_encoding(search_data, query):
    from app.modules.retrieval.schemas import RetrievalError
    from app.modules.retrieval.service import RetrievalService

    def forbidden():
        pytest.fail("Invalid queries must not invoke the model")

    service = RetrievalService(search_data.factory, FixedEmbedder(forbidden))
    with pytest.raises(RetrievalError, match="INVALID_QUERY"):
        asyncio.run(service.search(search_data.actor, [UUID(int=1)], query))


@pytest.mark.parametrize(
    "field,value", [("embedding_model", "other"), ("embedding_version", "old")]
)
def test_authorized_active_model_mismatch_requires_reindex(search_data, field, value):
    from app.modules.retrieval.schemas import RetrievalError

    data = search_data
    kb = data.kb()
    chunk = data.document(kb)[2]
    with data.factory() as db:
        db.execute(update(Chunk).where(Chunk.id == chunk).values({field: value}))
        db.commit()
    with pytest.raises(RetrievalError, match="MODEL_INDEX_MISMATCH"):
        search(data, [kb])


def test_unindexed_chunks_are_not_searchable(search_data):
    data = search_data
    kb = data.kb()
    chunk = data.document(kb)[2]
    with data.factory() as db:
        db.execute(
            update(Chunk)
            .where(Chunk.id == chunk)
            .values(embedding=None, embedding_model=None, embedding_version=None)
        )
        db.commit()
    assert search(data, [kb]) == []


def test_cpu_encoding_runs_off_event_loop_without_open_session(search_data):
    from threading import get_ident

    from app.modules.retrieval.service import RetrievalService

    data = search_data
    kb = data.kb()
    expected = data.document(kb)[2]
    event_loop_thread = get_ident()
    active_sessions = []
    base_session = data.factory.class_

    class ObservedSession(base_session):
        def __enter__(self):
            active_sessions.append(self)
            return super().__enter__()

        def __exit__(self, *args):
            active_sessions.remove(self)
            return super().__exit__(*args)

    from sqlalchemy.orm import sessionmaker

    observed_factory = sessionmaker(class_=ObservedSession, **data.factory.kw)

    def encode():
        assert get_ident() != event_loop_thread
        assert active_sessions == []

    service = RetrievalService(observed_factory, FixedEmbedder(encode))
    hits = asyncio.run(service.search(data.actor, [kb], "开放时间"))
    assert [hit.chunk_id for hit in hits] == [expected]


def test_initial_default_threshold_keeps_moderately_similar_evidence(search_data):
    from app.modules.retrieval.service import RetrievalService

    data = search_data
    kb = data.kb()
    expected = data.document(kb, score=0.7)[2]
    data.document(kb, score=0.6)
    service = RetrievalService(data.factory, FixedEmbedder())
    hits = asyncio.run(service.search(data.actor, [kb], "开放时间"))
    assert [hit.chunk_id for hit in hits] == [expected]
