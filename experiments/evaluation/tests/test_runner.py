import asyncio
import json
from pathlib import Path

import pytest
from experiments.evaluation.dataset import load_dataset
from experiments.evaluation.run_eval import evaluate_case

from app.modules.retrieval.service import RetrievalService
from tests.retrieval import search_helpers
from tests.retrieval.search_helpers import FixedEmbedder

search_data = search_helpers.search_data


def test_frozen_dataset_has_disjoint_source_groups_and_reference_spans(tmp_path):
    dataset = load_dataset(Path(__file__).resolve().parents[1] / "dataset.json")
    assert len(dataset["cases"]) == 60
    assert {case["split"] for case in dataset["cases"]} == {"dev", "test"}
    altered = json.loads(json.dumps(dataset))
    altered["cases"][0]["split"] = "test"
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(ValueError, match="split"):
        load_dataset(broken)


def test_runner_records_actual_permission_filtered_database_hits_without_generation(
    search_data,
):
    data = search_data
    visible, hidden = data.kb(), data.kb(member=False)
    source, _, chunk = data.document(visible, score=0.8, text="GH-204借阅柜位于东馆")
    secret, _, _ = data.document(hidden, text="GH-204借阅柜门禁口令")
    case = {
        "id": "literal-q1",
        "reference_sources": ["visible-source"],
        "expected_refusal": False,
        "question": "GH-204借阅柜在哪？",
        "retrieval_query": "GH-204借阅柜在哪？",
        "history": [],
        "answer_terms": ["东馆"],
    }
    service = RetrievalService(data.factory, FixedEmbedder(), mode="hybrid")
    row = asyncio.run(
        evaluate_case(
            case,
            data.actor,
            [visible, hidden],
            service,
            {source: "visible-source", secret: "secret-source"},
            provider=None,
        )
    )
    assert row["retrieved_sources"] == ["visible-source"]
    assert row["hits"][0]["chunk_id"] == str(chunk)
    assert row["hits"][0]["score"] == pytest.approx(0.8)
    assert row["unauthorized_sources"] == []
    assert row["answer_status"] is None
    assert row["citation_sources"] == []


def test_runner_records_real_rag_citation_event_and_term_coverage(search_data):
    from tests.rag.service_helpers import ScriptedProvider, answer, complete

    data = search_data
    kb = data.kb()
    source, _, _ = data.document(kb, text="GH-204借阅柜位于东馆")
    case = {
        "id": "rag-q1",
        "reference_sources": ["visible-source"],
        "expected_refusal": False,
        "question": "GH-204借阅柜在哪？",
        "retrieval_query": "GH-204借阅柜在哪？",
        "history": [],
        "answer_terms": ["东馆"],
    }
    provider = ScriptedProvider(complete(answer(quote="GH-204借阅柜位于东馆")))
    service = RetrievalService(data.factory, FixedEmbedder())
    row = asyncio.run(
        evaluate_case(
            case,
            data.actor,
            [kb],
            service,
            {source: "visible-source"},
            provider=provider,
        )
    )
    assert row["error"] is None
    assert row["answer_status"] == "answered"
    assert row["citation_sources"] == ["visible-source"]
    assert row["citation_mapped"] == [True]
    assert row["answer_term_coverage"] == 1.0


def test_build_index_uses_existing_index_handler_and_stable_source_ids(search_data, tmp_path):
    from types import SimpleNamespace

    from experiments.evaluation.run_eval import build_index, stable_id

    from app.modules.ingestion.models import Chunk
    from tests.ingestion.test_worker import tokenizer
    from tests.retrieval.test_indexing import FixedEmbedder as PassageEmbedder

    token_path = tmp_path / "tokenizer.json"
    tokenizer().save(str(token_path))
    dataset = {
        "sources": [
            {
                "id": "literal-source",
                "kb": "dev-public",
                "title": "借阅柜",
                "text": "借阅柜位于东馆",
            }
        ]
    }
    actor, kbs = build_index(
        search_data.factory,
        dataset,
        SimpleNamespace(embedding_tokenizer_path=str(token_path)),
        PassageEmbedder(),
    )
    with search_data.factory() as db:
        chunk = db.get(Chunk, stable_id("literal-source/chunk-0"))
        assert chunk.faq_id == stable_id("literal-source")
        assert chunk.text == "借阅柜\n借阅柜位于东馆"
        assert len(chunk.embedding) == 512
    assert actor.role == "user"
    assert kbs == {"dev-public": stable_id("dev-public")}
