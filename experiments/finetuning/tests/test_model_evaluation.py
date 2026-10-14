import asyncio
import importlib
import json

import pytest

from app.modules.providers.schemas import LLMDelta, LLMUsage


def evaluator():
    assert importlib.util.find_spec("experiments.finetuning.evaluate_model") is not None, (
        "separate grounded/general evaluator is missing"
    )
    return importlib.import_module("experiments.finetuning.evaluate_model")


class Provider:
    """No GPU/network: predetermined terminal events through real evaluator parsing."""

    def __init__(self, outputs, *, reason="stop", failure=False):
        self.outputs = iter(outputs)
        self.reason = reason
        self.failure = failure
        self.requests = []

    async def stream(self, messages, *, max_tokens, temperature):
        self.requests.append((messages, max_tokens, temperature))
        if self.failure:
            raise RuntimeError("private-key /private/location raw output")
        yield LLMDelta(text=next(self.outputs))
        yield LLMDelta(
            finish_reason=self.reason,
            usage=LLMUsage(prompt_tokens=41, completion_tokens=7, total_tokens=48),
        )


def general_case(task="arithmetic", expected="17"):
    return {
        "id": "original-one",
        "group": "math",
        "family": "sum",
        "split": "test",
        "task": task,
        "user_prompt": "只输出8+9的整数结果",
        "expected": {"match": "exact", "value": expected},
    }


def grounded_dataset(history=False):
    import hashlib

    text = "虚构星桥社的登记窗口在三层。"
    source = {
        "id": "original-source",
        "title": "虚构教学政策",
        "text": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "kb": "test-public",
        "split": "test",
        "group": "policy",
    }
    case = {
        "id": "original-case",
        "group": "policy",
        "family": "window",
        "split": "test",
        "question": "它的登记窗口在哪？" if history else "星桥社的登记窗口在哪？",
        "retrieval_query": "星桥社的登记窗口在哪？",
        "allowed_kbs": ["test-public"],
        "history": [
            {"role": "user", "content": "说说星桥社"},
            {"role": "assistant", "content": "错误旧答案：一层"},
        ]
        if history
        else [],
        "evidence": [{"index": 1, "source_id": "original-source"}],
        "answer": {"status": "answered", "selections": [{"index": 1, "quote": text}]},
        "rewrite": {"query": "星桥社的登记窗口在哪？", "needs_clarification": False},
        "reference_sources": ["original-source"],
        "reference_answer": text,
        "answer_terms": [text],
        "expected_refusal": False,
    }
    return {
        "schema_version": 2,
        "version": "original-fixture",
        "synthetic": True,
        "sources": [source],
        "cases": [case],
    }


def test_general_uses_own_prompt_without_expected():
    module = evaluator()
    case = general_case("instruction", expected="PRIVATE_REFERENCE")
    provider = Provider(["PRIVATE_REFERENCE"])
    rows = asyncio.run(
        module.evaluate_dataset(
            {"schema_version": 1, "mode": "general", "cases": [case]}, "general", "test", provider
        )
    )
    assert rows[0]["correct"] is True
    messages, output_limit, temperature = provider.requests[0]
    assert messages[0].content == "按用户要求完成任务，严格遵守要求的输出格式。"
    assert messages[1].content == "只输出8+9的整数结果"
    assert "PRIVATE_REFERENCE" not in "".join(m.content for m in messages)
    assert output_limit == 512 and temperature == 0


@pytest.mark.parametrize(
    "output,want",
    [("17", True), (" 17\n", True), ("17.0", False), ("+17", False), ("答案17", False)],
)
def test_general_arithmetic_exact(output, want):
    module = evaluator()
    assert module.score_general(output, general_case()) is want


def test_instruction_exact_format_does_not_discard_extra_whitespace():
    module = evaluator()
    case = general_case("instruction", expected="READY")
    assert module.score_general("READY", case) is True
    assert module.score_general("\nREADY\n", case) is False


@pytest.mark.parametrize(
    "output,want",
    [
        ('{"n":2,"ok":true,"extra":"allowed"}', True),
        ('{"n":2.0,"ok":true}', False),
        ('{"n":true,"ok":true}', False),
        ('{"n":2,"ok":1}', False),
        ('{"n":2,"n":2,"ok":true}', False),
        ('{"n":2,"ok":true,"bad":NaN}', False),
        ('```json\n{"n":2,"ok":true}\n```', False),
    ],
)
def test_general_json_subset_is_strict_and_type_aware(output, want):
    module = evaluator()
    case = general_case("json")
    case["expected"] = {"match": "json_subset", "value": {"n": 2, "ok": True}}
    assert module.score_general(output, case) is want


def test_quote_must_map_to_supplied_evidence():
    module = evaluator()
    dataset = grounded_dataset()
    provider = Provider(['{"status":"answered","selections":[{"index":1,"quote":"一层"}]}'])
    rows = asyncio.run(module.evaluate_dataset(dataset, "grounded", "test", provider))
    assert rows[0]["answer"]["error"] == "INVALID_CITATION"
    assert rows[0]["answer"]["reference_match"] is False
    assert rows[0]["answer"]["citation_mapping"] is None


def test_rewrite_uses_history_only_for_referent():
    module = evaluator()
    dataset = grounded_dataset(history=True)
    provider = Provider(
        [
            '{"status":"answered","selections":[{"index":1,"quote":"虚构星桥社的登记窗口在三层。"}]}',
            '{"query":"星桥社的登记窗口在哪？","needs_clarification":false}',
        ]
    )
    rows = asyncio.run(module.evaluate_dataset(dataset, "grounded", "test", provider))
    assert rows[0]["answer"]["reference_match"] is True
    assert rows[0]["rewrite"]["reference_match"] is True
    answer_input = json.loads(provider.requests[0][0][1].content)
    rewrite_input = json.loads(provider.requests[1][0][1].content)
    assert "history" not in answer_input
    assert answer_input["retrieval_query"] == "星桥社的登记窗口在哪？"
    assert rewrite_input["history"][1]["content"] == "错误旧答案：一层"
    assert "evidence" not in rewrite_input and "rewrite" not in rewrite_input


def test_finish_usage_errors_and_metric_divisors_are_actual():
    module = evaluator()
    cases = [general_case(), {**general_case(), "id": "second"}]
    rows = asyncio.run(
        module.evaluate_dataset(
            {"schema_version": 1, "mode": "general", "cases": cases},
            "general",
            "test",
            Provider(["17", "17"], reason="length"),
        )
    )
    assert rows[0]["finish_reason"] == "length"
    assert rows[0]["usage"] == {"prompt_tokens": 41, "completion_tokens": 7, "total_tokens": 48}
    assert rows[0]["correct"] is False
    summary = module.summarize_evaluation(rows, "general")
    assert summary["scored_count"] == 2 and summary["error_count"] == 2
    assert summary["accuracy"] == 0
    failure_rows = asyncio.run(
        module.evaluate_dataset(
            {"schema_version": 1, "mode": "general", "cases": [general_case()]},
            "general",
            "test",
            Provider([], failure=True),
        )
    )
    assert failure_rows[0]["error"] == "EVALUATION_PROVIDER_ERROR"
    assert "private" not in json.dumps(failure_rows)


def test_evaluation_dataset_hash_is_separate_from_training_hash(tmp_path):
    from test_local_evaluation import runtime_v2, write_runtime

    module = evaluator()
    path = tmp_path / "general.json"
    path.write_text(
        json.dumps({"schema_version": 1, "mode": "general", "cases": [general_case()]}),
        encoding="utf-8",
    )
    report = asyncio.run(
        module.evaluate_file(
            path, "general", "test", write_runtime(tmp_path, runtime_v2()), Provider(["17"])
        )
    )
    metadata = report["metadata"]
    assert metadata["evaluation_dataset_sha256"] != "c" * 64
    assert metadata["runtime_manifest"]["training_data_sha256"] == "c" * 64
    assert metadata["effective_greedy"] is None
    assert len(metadata["evaluation_code_sha256"]["evaluate_model.py"]) == 64
    assert len(metadata["evaluation_code_sha256"]["run_eval.py"]) == 64
    assert "user_prompt" not in json.dumps(report) and "expected" not in json.dumps(report)


def test_real_greedy_evidence_is_sanitized_but_never_inferred(tmp_path):
    from experiments.evaluation.run_eval import load_runtime_manifest
    from test_local_evaluation import runtime_v2, write_runtime

    value = runtime_v2()
    value["generation_evidence"] = {
        "mode": "GREEDY_SEARCH",
        "do_sample": False,
        "evidence_sha256": "e" * 64,
        "private_path": "/private/evidence",
    }
    result = load_runtime_manifest(write_runtime(tmp_path, value))
    assert result["generation_evidence"] == {
        "mode": "GREEDY_SEARCH",
        "do_sample": False,
        "evidence_sha256": "e" * 64,
    }


def test_general_request_guard_prevents_oversized_prompt_before_provider():
    module = evaluator()
    case = {**general_case(), "user_prompt": "大" * 5000}
    provider = Provider(["17"])
    rows = asyncio.run(
        module.evaluate_dataset(
            {"schema_version": 1, "mode": "general", "cases": [case]}, "general", "test", provider
        )
    )
    assert rows[0]["error"] == "INPUT_BYTE_LIMIT"
    assert provider.requests == []


def test_no_candidates_is_separate_from_bad_json():
    from types import SimpleNamespace

    from experiments.evaluation.run_eval import evaluate_case

    module = evaluator()
    dataset = grounded_dataset()
    case = dataset["cases"][0]

    class Retriever:
        def __init__(self, hits):
            self.hits = hits

        async def search_detailed(self, *args, **kwargs):
            return SimpleNamespace(hits=self.hits, rerank_status="disabled")

        async def validate_hits(self, *args):
            return True

    no_candidates = asyncio.run(evaluate_case(case, None, [], Retriever([]), {}, Provider([])))
    hit = module.supplied_hits(case, {s["id"]: s for s in dataset["sources"]})[0]
    bad_json = asyncio.run(
        evaluate_case(case, None, [], Retriever([hit]), {}, Provider(["not JSON"]))
    )
    assert no_candidates["generation_diagnosis"] == "no_candidates"
    assert bad_json["generation_diagnosis"] == "invalid_json"
    assert bad_json["generation_stages"][0]["finish_reason"] == "stop"
    assert bad_json["generation_stages"][0]["usage"]["total_tokens"] == 48


def test_v2_real_rag_public_rows_never_publish_prompt_labels_or_outputs():
    from experiments.evaluation import run_eval

    sanitize = getattr(run_eval, "public_rag_row", None)
    assert callable(sanitize), "v2 reports must filter original prompts and outputs"
    row = {
        "id": "original-case",
        "question": "private question",
        "answer": {"label": "secret"},
        "hits": [{"text": "private source"}],
        "answer_text": "raw output",
        "error": None,
        "citation_mapped": [True],
        "generation_diagnosis": "model_answered",
    }
    assert sanitize(row) == {
        "id": "original-case",
        "error": None,
        "citation_mapped": [True],
        "generation_diagnosis": "model_answered",
    }
    row["error"] = "/private/model/key accidentally surfaced"
    assert sanitize(row)["error"] == "EVALUATION_PIPELINE_ERROR"


@pytest.mark.parametrize(
    "bad",
    [
        '{"schema_version":1,"mode":"general","cases":[]}',
        '{"schema_version":1,"mode":"general","cases":[],"cases":[]}',
    ],
)
def test_general_loader_rejects_empty_or_duplicate_schema(tmp_path, bad):
    module = evaluator()
    path = tmp_path / "bad.json"
    path.write_text(bad, encoding="utf-8")
    with pytest.raises(ValueError):
        module.load_cases(path, "general")
