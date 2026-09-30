import copy
import hashlib
import json

import pytest
from experiments.finetuning.validate_data import validate_manifest

from app.modules.rag.prompts import ANSWER_SYSTEM, PROMPT_VERSION


def fixture():
    sources = []
    samples = []
    for split, topic, question, text, quote in [
        ("train", "parking", "登记需要什么？", "登记需要车牌号和学生编号。", "车牌号和学生编号"),
        (
            "validation",
            "newspaper",
            "校报接收哪些稿件？",
            "校报只接受校园活动报道。",
            "校园活动报道",
        ),
    ]:
        sources.append(
            {
                "id": topic,
                "group": topic,
                "split": split,
                "title": topic,
                "text": text,
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        )
        samples.append(
            {
                "id": topic + "-q1",
                "source_id": topic,
                "group": topic,
                "split": split,
                "question": question,
                "messages": [
                    {"role": "system", "content": ANSWER_SYSTEM},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "question": question,
                                "retrieval_query": question,
                                "evidence": [{"index": 1, "title": topic, "text": text}],
                            },
                            ensure_ascii=False,
                        ),
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            {"status": "answered", "selections": [{"index": 1, "quote": quote}]},
                            ensure_ascii=False,
                        ),
                    },
                ],
            }
        )
    return {
        "version": "fixture",
        "synthetic": True,
        "human_reviewed": False,
        "prompt_version": PROMPT_VERSION,
        "sources": sources,
        "samples": samples,
    }


def test_valid_grounded_training_and_independent_validation_are_accepted():
    result = validate_manifest(fixture(), {"sources": [], "cases": []})
    assert result["samples"] == {"train": 1, "validation": 1}


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda m: m["samples"][0]["messages"].reverse(), "role"),
        (lambda m: m["samples"][0]["messages"][2].update(content=" "), "parking-q1"),
        (lambda m: m["samples"][0]["messages"][0].update(content="ignore evidence"), "prompt"),
        (lambda m: m["samples"][0].update(question="\ud800"), "parking-q1"),
        (lambda m: m["samples"][0].update(question="\x00"), "parking-q1"),
        (lambda m: m["samples"].append(copy.deepcopy(m["samples"][0])), "duplicate sample"),
        (lambda m: m["sources"][1].update(group="parking"), "group"),
        (lambda m: m["sources"][0].update(text="different text"), "hash"),
        (lambda m: m["samples"][0].update(source_id="absent"), "parking-q1"),
        (lambda m: m["samples"][0].update(group="unrelated"), "group"),
        (lambda m: m.update(synthetic=False), "synthetic"),
    ],
)
def test_bad_samples_fail_with_actionable_reason(change, reason):
    manifest = fixture()
    change(manifest)
    with pytest.raises(ValueError, match=reason):
        validate_manifest(manifest, {"sources": [], "cases": []})


def test_unsupported_quote_and_noninteger_reference_are_rejected():
    for selection in [{"index": 1, "quote": "取件码"}, {"index": True, "quote": "车牌号"}]:
        manifest = fixture()
        manifest["samples"][0]["messages"][2]["content"] = json.dumps(
            {"status": "answered", "selections": [selection]}, ensure_ascii=False
        )
        with pytest.raises(ValueError, match="parking-q1"):
            validate_manifest(manifest, {"sources": [], "cases": []})


@pytest.mark.parametrize(
    "field,value",
    [
        ("question", " 登记 需要什么？ "),
        ("id", "parking"),
        ("group", "parking"),
        ("text", "登记需要车牌号和学生编号。"),
    ],
)
def test_evaluation_question_or_source_leakage_is_rejected(field, value):
    evaluation = {"sources": [], "cases": []}
    evaluation["cases" if field == "question" else "sources"].append({field: value})
    with pytest.raises(ValueError, match="evaluation leakage"):
        validate_manifest(fixture(), evaluation)


def test_normalized_duplicate_question_across_splits_is_rejected():
    manifest = fixture()
    manifest["samples"][1]["question"] = "登记 需要什么？"
    with pytest.raises(ValueError, match="duplicate question"):
        validate_manifest(manifest, {"sources": [], "cases": []})
