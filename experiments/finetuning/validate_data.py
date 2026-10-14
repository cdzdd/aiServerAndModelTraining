# ruff: noqa: E402
"""Validate explicitly synthetic grounded teaching manifest v1 and corpus v2."""

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.modules.rag.prompts import ANSWER_SYSTEM, PROMPT_VERSION


def normalized(value):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value).casefold())


def require_text(value, label):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{label}: nonempty valid text required")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{label}: invalid Unicode") from None


def context_normalized(value):
    """Ignore renamed ASCII identifiers/numbers when screening complete contexts."""
    return normalized(re.sub(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", "", value))


def reject_context_duplicates(entries):
    # Character 4-gram Jaccard is a deterministic screening rule, not a semantic model.
    # Family/semantic groups and independent review cover paraphrases this rule misses.
    index, prior = {}, []
    for identity, split, text in entries:
        norm = context_normalized(text)
        grams = {norm[i : i + 4] for i in range(max(1, len(norm) - 3))}
        overlaps = Counter()
        for gram in grams:
            for number in index.get(gram, []):
                if prior[number][1] != split:
                    overlaps[number] += 1
        for number, overlap in overlaps.items():
            other, _, other_grams = prior[number]
            if overlap / len(grams | other_grams) >= 0.88:
                raise ValueError(f"context cross-split duplicate: {other} / {identity}")
        number = len(prior)
        prior.append((identity, split, grams))
        for gram in grams:
            index.setdefault(gram, []).append(number)


def validate_corpus(corpus):
    """Validate raw v2 labels before projection; history never supplies evidence."""
    if corpus.get("schema_version") != 2:
        raise ValueError("corpus schema_version must be 2")
    if corpus.get("synthetic") is not True or corpus.get("human_reviewed") is not False:
        raise ValueError("explicit synthetic data without claimed human review required")
    if corpus.get("prompt_version") != PROMPT_VERSION:
        raise ValueError("production prompt version mismatch")
    sources, split_groups, contexts = {}, {}, []
    for source in corpus["sources"]:
        label = f"source {source.get('id')}"
        for field in (
            "id",
            "group",
            "family",
            "semantic_group",
            "split",
            "title",
            "text",
            "sha256",
            "license",
            "authorization",
            "provenance",
            "kb",
        ):
            require_text(source.get(field), f"{label}: {field}")
        if source["id"] in sources:
            raise ValueError(f"{label}: duplicate source ID")
        if source["split"] not in {"train", "dev", "test"}:
            raise ValueError(f"{label}: invalid split")
        if source["license"] != "original-synthetic-project-use":
            raise ValueError(f"{label}: original synthetic project license required")
        if source["visibility"] != "public" or source["kb"] != source["split"] + "-public":
            raise ValueError(f"{label}: synthetic public kb mismatch")
        if hashlib.sha256(source["text"].encode()).hexdigest() != source["sha256"]:
            raise ValueError(f"{label}: hash mismatch")
        for field in ("group", "family", "semantic_group"):
            key = (field, source[field])
            if split_groups.setdefault(key, source["split"]) != source["split"]:
                raise ValueError(f"{field} crosses split: {source[field]}")
        sources[source["id"]] = source
        contexts.append((source["id"], source["split"], source["text"]))
    reject_context_duplicates(contexts)
    counts, projections, ids, complete_contexts = Counter(), Counter(), set(), []
    for case in corpus["cases"]:
        label = f"case {case.get('id')}"
        for field in (
            "id",
            "source_id",
            "group",
            "family",
            "semantic_group",
            "split",
            "question",
            "retrieval_query",
        ):
            require_text(case.get(field), f"{label}: {field}")
        if case["id"] in ids:
            raise ValueError(f"{label}: duplicate case ID")
        ids.add(case["id"])
        source = sources.get(case["source_id"])
        if source is None:
            raise ValueError(f"{label}: missing source")
        if any(
            case[field] != source[field] for field in ("group", "family", "semantic_group", "split")
        ):
            raise ValueError(f"{label}: source split/group/family mismatch")
        history = case.get("history")
        if not isinstance(history, list) or len(history) % 2 or len(history) > 6:
            raise ValueError(f"{label}: history must contain at most three user/assistant pairs")
        for number, message in enumerate(history):
            if (
                not isinstance(message, dict)
                or set(message) != {"role", "content"}
                or message["role"] != ("user" if number % 2 == 0 else "assistant")
            ):
                raise ValueError(f"{label}: invalid history pair")
            require_text(message["content"], label + ": history")
        evidence, evidence_ids = {}, []
        if not isinstance(case.get("evidence"), list) or not 1 <= len(case["evidence"]) <= 5:
            raise ValueError(f"{label}: one to five evidence candidates required")
        for position, item in enumerate(case["evidence"], 1):
            if (
                not isinstance(item, dict)
                or set(item) != {"index", "source_id"}
                or type(item["index"]) is not int
                or item["index"] <= 0
                or item["index"] in evidence
            ):
                raise ValueError(f"{label}: unique positive integer evidence index required")
            if item["index"] != position:
                raise ValueError(f"{label}: evidence indices must be production order 1..N")
            document = sources.get(item["source_id"])
            if document is None or any(
                document[field] != case[field]
                for field in ("group", "family", "semantic_group", "split")
            ):
                raise ValueError(f"{label}: evidence source split/group mismatch")
            if item["source_id"] in evidence_ids:
                raise ValueError(f"{label}: duplicate evidence source")
            evidence[item["index"]] = document
            evidence_ids.append(item["source_id"])
        answer = case.get("answer")
        if (
            not isinstance(answer, dict)
            or set(answer) != {"status", "selections"}
            or answer["status"] not in {"answered", "clarify", "no_answer"}
            or not isinstance(answer["selections"], list)
        ):
            raise ValueError(f"{label}: answer schema mismatch")
        selections = answer["selections"]
        if answer["status"] != "answered" and selections:
            raise ValueError(f"{label}: nonanswered requires empty selections")
        if answer["status"] == "answered" and not 1 <= len(selections) <= 3:
            raise ValueError(f"{label}: answered requires one to three selections")
        selected_ids, selected_indices, quotes = [], set(), []
        for selection in selections:
            if (
                not isinstance(selection, dict)
                or set(selection) != {"index", "quote"}
                or type(selection["index"]) is not int
                or selection["index"] not in evidence
                or selection["index"] in selected_indices
            ):
                raise ValueError(f"{label}: invalid or repeated selection index")
            selected_indices.add(selection["index"])
            require_text(selection["quote"], label + ": quote")
            document = evidence[selection["index"]]
            if selection["quote"] not in document["text"]:
                raise ValueError(f"{label}: quote is not a supported continuous source span")
            selected_ids.append(document["id"])
            quotes.append(selection["quote"])
        if sum(map(len, quotes)) > 800:
            raise ValueError(f"{label}: total quotes exceed 800 characters")
        if (
            case.get("reference_sources") != selected_ids
            or case.get("answer_terms") != quotes
            or case.get("reference_answer") != "；".join(quotes)
        ):
            raise ValueError(f"{label}: reference labels mismatch")
        if (
            type(case.get("expected_refusal")) is not bool
            or case["expected_refusal"] != (answer["status"] != "answered")
            or case.get("allowed_kbs") != [case["split"] + "-public"]
        ):
            raise ValueError(f"{label}: refusal/authorization mismatch")
        rewrite = case.get("rewrite")
        if rewrite is not None:
            if (
                not isinstance(rewrite, dict)
                or set(rewrite) != {"query", "needs_clarification"}
                or type(rewrite["needs_clarification"]) is not bool
            ):
                raise ValueError(f"{label}: rewrite needs_clarification must be boolean")
            if rewrite["needs_clarification"]:
                if rewrite["query"] != "" or answer["status"] != "clarify":
                    raise ValueError(f"{label}: ambiguous rewrite requires empty query and clarify")
            elif rewrite["query"] != case["retrieval_query"]:
                raise ValueError(f"{label}: rewrite query differs from retrieval_query")
            projections[case["split"]] += 1
        counts[case["split"]] += 1
        projections[case["split"]] += 1
        complete_contexts.append(
            (
                case["id"],
                case["split"],
                case["question"]
                + json.dumps(history, ensure_ascii=False)
                + "".join(sources[identity]["text"] for identity in evidence_ids),
            )
        )
    if not all(counts[split] for split in ("train", "dev", "test")):
        raise ValueError("train/dev/test cases required")
    reject_context_duplicates(complete_contexts)
    return {
        "cases": dict(counts),
        "samples": dict(projections),
        "sources": len(sources),
        "groups": sum(key[0] == "group" for key in split_groups),
        "families": sum(key[0] == "family" for key in split_groups),
        "context_screen": (
            "ASCII-identifiers stripped; character4 Jaccard>=0.88; "
            "independent semantic audit required"
        ),
    }


def validate_manifest(manifest, evaluation):
    if manifest.get("synthetic") is not True or manifest.get("human_reviewed") is not False:
        raise ValueError("explicit synthetic data without claimed human review required")
    if manifest.get("prompt_version") != PROMPT_VERSION:
        raise ValueError("production prompt version mismatch")
    sources = {}
    groups = {}
    source_texts = set()
    for source in manifest["sources"]:
        for field in ("id", "group", "split", "title", "text", "sha256"):
            require_text(source.get(field), f"source {source.get('id')}: {field}")
        if source["id"] in sources:
            raise ValueError("duplicate source ID")
        if source["split"] not in {"train", "validation"}:
            raise ValueError("invalid source split")
        if hashlib.sha256(source["text"].encode()).hexdigest() != source["sha256"]:
            raise ValueError(f"source {source['id']}: hash mismatch")
        norm = normalized(source["text"])
        if norm in source_texts:
            raise ValueError("duplicate normalized source text")
        source_texts.add(norm)
        previous = groups.setdefault(source["group"], source["split"])
        if previous != source["split"]:
            raise ValueError("source group crosses split")
        sources[source["id"]] = source
    ids, questions = set(), set()
    counts = Counter()
    for sample in manifest["samples"]:
        label = f"sample {sample.get('id')}"
        for field in ("id", "group", "split", "question", "source_id"):
            require_text(sample.get(field), f"{label}: {field}")
        if sample["id"] in ids:
            raise ValueError(f"{label}: duplicate sample ID")
        ids.add(sample["id"])
        question = normalized(sample["question"])
        if question in questions:
            raise ValueError(f"{label}: duplicate question")
        questions.add(question)
        source = sources.get(sample["source_id"])
        if source is None:
            raise ValueError(f"{label}: missing source")
        if sample["split"] != source["split"] or sample["group"] != source["group"]:
            raise ValueError(f"{label}: source split/group mismatch")
        messages = sample.get("messages")
        if (
            not isinstance(messages, list)
            or len(messages) != 3
            or any(not isinstance(m, dict) for m in messages)
            or [m.get("role") for m in messages] != ["system", "user", "assistant"]
        ):
            raise ValueError(f"{label}: role order must be system/user/assistant")
        for message in messages:
            require_text(message.get("content"), label)
            if set(message) != {"role", "content"}:
                raise ValueError(f"{label}: message schema mismatch")
        if messages[0]["content"] != ANSWER_SYSTEM:
            raise ValueError(f"{label}: system prompt mismatch")
        try:
            user = json.loads(messages[1]["content"])
            answer = json.loads(messages[2]["content"])
        except (ValueError, TypeError):
            raise ValueError(f"{label}: invalid JSON") from None
        expected = {
            "question": sample["question"],
            "retrieval_query": sample["question"],
            "evidence": [{"index": 1, "title": source["title"], "text": source["text"]}],
        }
        if user != expected:
            raise ValueError(f"{label}: evidence/question mismatch")
        if (
            not isinstance(answer, dict)
            or set(answer) != {"status", "selections"}
            or (
                answer["status"] != "answered"
                or not isinstance(answer["selections"], list)
                or len(answer["selections"]) != 1
            )
        ):
            raise ValueError(f"{label}: answer schema mismatch")
        selection = answer["selections"][0]
        if (
            not isinstance(selection, dict)
            or set(selection) != {"index", "quote"}
            or (type(selection["index"]) is not int or selection["index"] != 1)
        ):
            raise ValueError(f"{label}: invalid selection reference")
        require_text(selection["quote"], label)
        if selection["quote"] not in source["text"] or len(selection["quote"]) > 800:
            raise ValueError(f"{label}: quote is not a supported continuous source span")
        counts[sample["split"]] += 1
    if not counts["train"] or not counts["validation"]:
        raise ValueError("both train and validation samples required")
    for source in evaluation["sources"]:
        if (
            source.get("id") in sources
            or source.get("group") in groups
            or (source.get("text") and normalized(source["text"]) in source_texts)
        ):
            raise ValueError("evaluation leakage: source identity/group/text")
    if any(normalized(case["question"]) in questions for case in evaluation["cases"]):
        raise ValueError("evaluation leakage: normalized question")
    return {"samples": dict(counts), "sources": len(sources), "groups": len(groups)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--evaluation", type=Path, default=ROOT / "experiments/evaluation/dataset.json"
    )
    args = parser.parse_args()
    result = validate_manifest(
        json.loads(args.manifest.read_text(encoding="utf-8-sig")),
        json.loads(args.evaluation.read_text(encoding="utf-8-sig")),
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
