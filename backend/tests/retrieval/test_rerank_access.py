import asyncio
import time

import pytest
from sqlalchemy import delete

from app.modules.knowledge.models import KnowledgeMembership
from app.modules.retrieval.service import RetrievalService
from tests.retrieval import search_helpers
from tests.retrieval.search_helpers import FixedEmbedder

search_data = search_helpers.search_data


class SlowReranker:
    def rank(self, query, hits):
        time.sleep(0.15)
        return list(reversed(hits))


class BrokenReranker:
    def rank(self, query, hits):
        raise RuntimeError("local model unavailable")


@pytest.mark.parametrize("reranker", [SlowReranker(), BrokenReranker()])
def test_timeout_and_unavailable_rerank_fall_back_to_authorized_order(search_data, reranker):
    data = search_data
    visible = data.kb()
    hidden = data.kb(member=False)
    first = data.document(visible, score=0.95, text="借阅柜")[2]
    data.document(hidden, text="借阅柜私密")
    service = RetrievalService(
        data.factory, FixedEmbedder(), mode="hybrid", reranker=reranker, rerank_timeout=0.02
    )
    outcome = asyncio.run(service.search_detailed(data.actor, [visible, hidden], "借阅柜"))
    assert [hit.chunk_id for hit in outcome.hits] == [first]
    assert outcome.rerank_status in {"timeout", "unavailable"}


def test_authority_is_checked_again_after_reranking(search_data):
    data = search_data
    kb = data.kb()
    data.document(kb, text="借阅柜")

    class RevokingReranker:
        def rank(self, query, hits):
            with data.factory() as db:
                db.execute(delete(KnowledgeMembership).where(KnowledgeMembership.kb_id == kb))
                db.commit()
            return hits

    service = RetrievalService(
        data.factory, FixedEmbedder(), mode="hybrid", reranker=RevokingReranker()
    )
    assert asyncio.run(service.search(data.actor, [kb], "借阅柜")) == []


def test_local_cross_encoder_rejects_unverified_snapshot_before_loading(tmp_path):
    from app.modules.retrieval.reranker import LocalCrossEncoder

    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="RERANK_INTEGRITY"):
        LocalCrossEncoder(str(tmp_path)).rank("借阅柜", [])
