import asyncio

import pytest

from app.modules.retrieval.service import RetrievalService
from tests.retrieval import search_helpers
from tests.retrieval.search_helpers import FixedEmbedder

search_data = search_helpers.search_data


def test_chinese_identifier_lexical_candidate_is_fused_with_cosine_score(search_data):
    data = search_data
    kb = data.kb()
    for i in range(20):
        data.document(kb, score=0.95, text=f"普通校园服务资料{i}")
    target = data.document(kb, score=0.8, text="星河校园借阅柜编号GH-204，位于东馆")[2]
    service = RetrievalService(data.factory, FixedEmbedder(), mode="hybrid")
    hits = asyncio.run(service.search(data.actor, [kb], "GH-204借阅柜", top_k=5))
    assert hits[0].chunk_id == target
    assert hits[0].score == pytest.approx(0.8)
    assert len(hits) == 5


def test_lexical_route_never_bypasses_authority_active_source_or_threshold(search_data):
    data = search_data
    visible = data.kb()
    private = data.kb(member=False)
    expected = data.document(visible, score=0.8, text="GH-204借阅柜")[2]
    data.document(private, text="GH-204借阅柜私密口令")
    data.document(visible, status="disabled", text="GH-204借阅柜旧资料")
    data.document(visible, score=0.1, text="GH-204借阅柜无语义依据")
    service = RetrievalService(data.factory, FixedEmbedder(), mode="hybrid")
    hits = asyncio.run(service.search(data.actor, [visible, private], "GH-204借阅柜"))
    assert [hit.chunk_id for hit in hits] == [expected]
    assert asyncio.run(service.search(data.actor, [], "GH-204借阅柜")) == []
