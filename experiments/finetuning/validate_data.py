"""Validate only the explicitly synthetic, reviewed-format teaching experiment."""

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

from app.modules.rag.prompts import ANSWER_SYSTEM, PROMPT_VERSION  # noqa: E402


def normalized(value):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value).casefold())


def require_text(value, label):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{label}: nonempty valid text required")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{label}: invalid Unicode") from None


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
