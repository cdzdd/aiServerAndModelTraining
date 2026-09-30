import pytest
from experiments.evaluation.metrics import summarize


def test_hand_calculated_retrieval_citation_and_refusal_denominators():
    rows = [
        {
            "reference_sources": ["a", "b"],
            "retrieved_sources": ["x", "b", "a"],
            "expected_refusal": False,
            "answer_status": "answered",
            "citation_sources": ["b", "x"],
            "citation_mapped": [True, True],
            "unauthorized_sources": [],
            "latency_ms": 10,
        },
        {
            "reference_sources": ["c"],
            "retrieved_sources": ["x"],
            "expected_refusal": False,
            "answer_status": "no_answer",
            "citation_sources": [],
            "citation_mapped": [],
            "unauthorized_sources": [],
            "latency_ms": 30,
        },
        {
            "reference_sources": [],
            "retrieved_sources": [],
            "expected_refusal": True,
            "answer_status": "no_answer",
            "citation_sources": [],
            "citation_mapped": [],
            "unauthorized_sources": [],
            "latency_ms": 20,
        },
    ]
    result = summarize(rows, k=2)
    assert result["recall_at_k"] == pytest.approx(0.25)
    assert result["mrr"] == pytest.approx(0.25)
    assert result["citation_correctness"] == pytest.approx(0.5)
    assert result["citation_mapping"] == 1.0
    assert result["refusal_accuracy"] == pytest.approx(2 / 3)
    assert result["false_answer_count"] == 0
    assert result["false_refusal_count"] == 1
    assert result["retrieval_denominator"] == 2
    assert result["citation_denominator"] == 2
    assert result["p50_latency_ms"] == 20
    assert result["p95_latency_ms"] == 29


def test_no_reference_or_generation_is_unknown_and_leaks_are_counted():
    result = summarize(
        [
            {
                "reference_sources": [],
                "retrieved_sources": ["secret"],
                "expected_refusal": True,
                "answer_status": None,
                "citation_sources": [],
                "citation_mapped": [],
                "unauthorized_sources": ["secret"],
                "latency_ms": 1,
            }
        ],
        k=5,
    )
    assert result["recall_at_k"] is None
    assert result["mrr"] is None
    assert result["citation_correctness"] is None
    assert result["citation_mapping"] is None
    assert result["refusal_accuracy"] is None
    assert result["permission_leaks"] == 1


def test_generation_error_is_never_a_correct_refusal():
    result = summarize(
        [
            {
                "reference_sources": [],
                "retrieved_sources": [],
                "expected_refusal": True,
                "answer_status": "error",
                "citation_sources": [],
                "citation_mapped": [],
                "unauthorized_sources": [],
                "latency_ms": 1,
                "error": "RAG_TIMEOUT",
            }
        ]
    )
    assert result["refusal_accuracy"] == 0.0
    assert result["error_count"] == 1


def test_answerable_generation_error_is_separate_from_false_refusal():
    result = summarize(
        [
            {
                "reference_sources": ["a"],
                "retrieved_sources": ["a"],
                "expected_refusal": False,
                "answer_status": "error",
                "citation_sources": [],
                "citation_mapped": [],
                "unauthorized_sources": [],
                "latency_ms": 1,
                "error": "RAG_TIMEOUT",
            }
        ]
    )
    assert result["false_refusal_count"] == 0
    assert result["error_count"] == 1
    assert result["refusal_accuracy"] == 0.0
