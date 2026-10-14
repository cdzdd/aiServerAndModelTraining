# ruff: noqa: E402
"""Offline given-evidence/rewrite and ordinary-instruction evaluation, separate from real RAG."""

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from contextlib import aclosing
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from experiments.evaluation.dataset import load_dataset
from experiments.evaluation.run_eval import (
    GENERAL_SYSTEM,
    TracedProvider,
    evaluation_code_hashes,
    load_runtime_manifest,
    prompt_hashes,
    public_stage,
    safe_error,
    select_generation_provider,
    stable_id,
    strict_json,
)

from app.modules.providers.config import ModelSettings
from app.modules.providers.schemas import LLMMessage
from app.modules.rag.citations import validate_selection
from app.modules.rag.prompts import (
    PROMPT_VERSION,
    build_answer_prompt,
    build_rewrite_prompt,
)
from app.modules.rag.schemas import RAGError
from app.modules.retrieval.schemas import SearchHit


def json_subset(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return all(
            key in actual and json_subset(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            json_subset(left, right) for left, right in zip(actual, expected, strict=True)
        )
    return actual == expected


def score_general(raw, case):
    expected = case["expected"]
    if expected["match"] == "exact":
        text = raw.strip() if case["task"] == "arithmetic" else raw
        if case["task"] == "arithmetic" and not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", text):
            return False
        return text == expected["value"]
    try:
        return json_subset(strict_json(raw), expected["value"])
    except (ValueError, TypeError, RecursionError):
        return False


def load_cases(path, mode):
    if mode == "grounded":
        dataset = load_dataset(path)
        if dataset.get("schema_version") != 2:
            raise ValueError("grounded evaluation requires the explicit corpus v2 schema")
        sources = {source["id"]: source for source in dataset["sources"]}
        for case in dataset["cases"]:
            if not isinstance(case.get("answer"), dict) or not isinstance(
                case.get("rewrite"), dict
            ):
                raise ValueError("grounded case requires frozen answer/rewrite references")
            evidence = case.get("evidence")
            if (
                not isinstance(evidence, list)
                or len(evidence) > 5
                or any(
                    type(item.get("index")) is not int
                    or item["index"] != index
                    or item.get("source_id") not in sources
                    or sources[item["source_id"]]["split"] != case["split"]
                    or sources[item["source_id"]]["kb"] not in case["allowed_kbs"]
                    for index, item in enumerate(evidence, 1)
                )
            ):
                raise ValueError(
                    "grounded supplied evidence must retain source/split/index identity"
                )
        return dataset
    dataset = strict_json(Path(path).read_bytes())
    if (
        dataset.get("schema_version") != 1
        or dataset.get("mode") != "general"
        or not isinstance(dataset.get("cases"), list)
        or not dataset["cases"]
    ):
        raise ValueError("general evaluation requires schema_version=1, mode=general and cases")
    seen = set()
    groups = {}
    for case in dataset["cases"]:
        expected = case.get("expected", {})
        if (
            not all(
                isinstance(case.get(key), str) and case[key]
                for key in ("id", "group", "family", "user_prompt")
            )
            or case["id"] in seen
            or case.get("split") != "test"
            or case.get("task") not in {"instruction", "arithmetic", "json"}
            or set(expected) != {"match", "value"}
            or expected["match"] not in {"exact", "json_subset"}
            or (expected["match"] == "exact" and not isinstance(expected["value"], str))
            or (
                case["task"] == "arithmetic"
                and (
                    expected["match"] != "exact"
                    or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", expected["value"])
                )
            )
            or (expected["match"] == "json_subset" and case["task"] != "json")
        ):
            raise ValueError("invalid frozen general case or reference")
        seen.add(case["id"])
        groups.setdefault(case["group"], set()).add(case["split"])
    if any(len(splits) > 1 for splits in groups.values()):
        raise ValueError("general groups cross split")
    return dataset


async def complete(trace, messages, max_tokens):
    text, terminal = "", False
    error = None
    try:
        async with aclosing(trace.stream(messages, max_tokens=max_tokens, temperature=0)) as stream:
            async for delta in stream:
                if terminal:
                    raise RAGError("PROVIDER_PROTOCOL_ERROR")
                text += delta.text
                if delta.finish_reason is not None:
                    terminal = True
                    if delta.finish_reason != "stop":
                        error = "PROVIDER_UNSUPPORTED_RESPONSE"
        if not terminal:
            error = "PROVIDER_STREAM_INTERRUPTED"
        elif not text.strip() and error is None:
            error = "PROVIDER_EMPTY_RESPONSE"
    except Exception as exc:  # noqa: BLE001 - retain only safe error codes
        error = safe_error(exc)
    stage = public_stage(trace.records[-1])
    stage["error"] = error
    return text, stage


def supplied_hits(case, sources):
    return [
        SearchHit(
            chunk_id=stable_id(item["source_id"] + "/golden"),
            kb_id=stable_id(sources[item["source_id"]]["kb"]),
            source_id=stable_id(item["source_id"]),
            source_type="faq",
            faq_version=1,
            title=sources[item["source_id"]]["title"],
            text=sources[item["source_id"]]["text"],
            score=1.0,
        )
        for item in case["evidence"]
    ]


async def evaluate_dataset(dataset, mode, split, provider, *, private_records=None):
    rows = []
    sources = {source["id"]: source for source in dataset.get("sources", [])}
    for case in dataset["cases"]:
        if case["split"] != split:
            continue
        trace = TracedProvider(provider)
        row = {"id": case["id"], "task": case.get("task", "grounded")}
        if mode == "general":
            messages = [
                LLMMessage(role="system", content=GENERAL_SYSTEM),
                LLMMessage(role="user", content=case["user_prompt"]),
            ]
            raw, stage = await complete(trace, messages, 512)
            row.update(stage)
            row["correct"] = stage["error"] is None and score_general(raw, case)
        else:
            hits = supplied_hits(case, sources)
            try:
                messages, retained = build_answer_prompt(
                    case["question"], hits, retrieval_query=case["retrieval_query"]
                )
                raw, answer = await complete(trace, messages, 512)
                answer.update(
                    {
                        "status": None,
                        "reference_match": False,
                        "citation_count": 0,
                        "citation_mapping": None,
                        "evidence_count": len(retained),
                        "golden_evidence_count": len(hits),
                        "diagnosis": "no_supplied_evidence" if not hits else None,
                    }
                )
                if answer["error"] is None:
                    try:
                        strict_json(raw)
                    except (ValueError, TypeError, RecursionError):
                        answer["error"] = "INVALID_JSON"
                    if answer["error"] is None:
                        try:
                            status, citations, _ = validate_selection(raw, retained)
                            answer.update(
                                {
                                    "status": status,
                                    "citation_count": len(citations),
                                    "citation_mapping": 1.0 if citations else None,
                                }
                            )
                            actual = {
                                "status": status,
                                "selections": [
                                    {"index": citation.index, "quote": citation.quote}
                                    for citation in citations
                                ],
                            }
                            answer["reference_match"] = json_subset(actual, case["answer"])
                            answer["diagnosis"] = "model_" + status
                        except RAGError:
                            answer["error"] = "INVALID_CITATION"
                if answer["error"]:
                    answer["diagnosis"] = answer["error"].lower()
            except RAGError as exc:
                answer = {
                    "error": safe_error(exc),
                    "reference_match": False,
                    "citation_count": 0,
                    "citation_mapping": None,
                    "status": None,
                }
            row["answer"] = answer
            if case["history"]:
                try:
                    messages = build_rewrite_prompt(
                        case["question"], [LLMMessage(**message) for message in case["history"]]
                    )
                    raw, rewrite = await complete(trace, messages, 128)
                    rewrite["reference_match"] = False
                    if rewrite["error"] is None:
                        try:
                            value = strict_json(raw)
                            if (
                                not isinstance(value, dict)
                                or set(value) != {"query", "needs_clarification"}
                                or type(value["needs_clarification"]) is not bool
                                or not isinstance(value["query"], str)
                                or (value["needs_clarification"] and value["query"] != "")
                                or (
                                    not value["needs_clarification"]
                                    and not 1 <= len(value["query"].strip()) <= 2000
                                )
                            ):
                                raise ValueError("invalid rewrite")
                            rewrite["reference_match"] = json_subset(value, case["rewrite"])
                        except (ValueError, TypeError, RecursionError):
                            rewrite["error"] = "INVALID_REWRITE"
                except RAGError as exc:
                    rewrite = {"error": safe_error(exc), "reference_match": False}
                row["rewrite"] = rewrite
            else:
                row["rewrite"] = None  # Production skips a model rewrite without retained history.
        rows.append(row)
        if private_records is not None:
            private_records.append({"id": case["id"], "stages": trace.records})
    return rows


def summarize_evaluation(rows, mode):
    def metrics(stages, field):
        count = len(stages)
        return {
            "scored_count": count,
            "correct_count": sum(bool(s.get(field)) for s in stages),
            "accuracy": sum(bool(s.get(field)) for s in stages) / count if count else None,
            "error_count": sum(s.get("error") is not None for s in stages),
            "finish_reason_counts": dict(Counter(s.get("finish_reason") for s in stages)),
            "error_counts": dict(Counter(s["error"] for s in stages if s.get("error"))),
        }

    if mode == "general":
        return metrics(rows, "correct")
    answers = [row["answer"] for row in rows]
    rewrites = [row["rewrite"] for row in rows if row["rewrite"] is not None]
    count = sum(stage["citation_count"] for stage in answers)
    return {
        "case_count": len(rows),
        "answer": metrics(answers, "reference_match"),
        "rewrite": metrics(rewrites, "reference_match"),
        "rewrite_not_applicable_count": len(rows) - len(rewrites),
        "citation_count": count,
        "citation_mapping": 1.0 if count else None,
        "limit": "exact frozen-reference/format scores; no independent semantic-quality claim",
    }


async def evaluate_file(path, mode, split, runtime_path, provider, *, private_records=None):
    runtime = load_runtime_manifest(runtime_path)
    dataset = load_cases(path, mode)
    rows = await evaluate_dataset(dataset, mode, split, provider, private_records=private_records)
    if not rows:
        raise ValueError("selected evaluation split has no cases")
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True))
    return {
        "metadata": {
            "schema_version": 1,
            "mode": mode,
            "split": split,
            "evaluation_path": "given_evidence_and_rewrite"
            if mode == "grounded"
            else "ordinary_instructions",
            "created_at": datetime.now(UTC).isoformat(),
            "evaluation_dataset_sha256": digest,
            "evaluation_code_sha256": evaluation_code_hashes(),
            "dataset_sha256": digest,
            "dataset_version": dataset.get("version", dataset["schema_version"]),
            "runtime_manifest": runtime,
            "code_commit": commit,
            "working_tree_dirty": dirty,
            "prompt_version": PROMPT_VERSION if mode == "grounded" else "general-regression-v1",
            "prompt_sha256": prompt_hashes(),
            "input_byte_limit": 12000,
            "answer_output_token_limit": 512,
            "rewrite_output_token_limit": 128,
            "effective_greedy": runtime.get("generation_evidence"),
            "generation_randomness": "temperature=0 requested; effective mode only "
            "as caller-verified evidence, never server authentication",
            "synthetic": True,
            "human_reviewed": False,
        },
        "summary": summarize_evaluation(rows, mode),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["grounded", "general"], required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--runtime-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    provider = select_generation_provider(ModelSettings(), generate=True, local_openai=True)
    private_records = []
    report = asyncio.run(
        evaluate_file(
            args.dataset,
            args.mode,
            args.split,
            args.runtime_manifest,
            provider,
            private_records=private_records,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.output.resolve().is_relative_to((ROOT / ".local").resolve()):
        args.output.with_suffix(".private.json").write_text(
            json.dumps(private_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report["summary"], ensure_ascii=False))
    summary = report["summary"]
    return int(
        bool(
            summary["error_count"]
            if args.mode == "general"
            else summary["answer"]["error_count"] + summary["rewrite"]["error_count"]
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
