"""Load the frozen teaching fixture and reject split/reference drift."""

import hashlib
import json
from pathlib import Path


def load_dataset(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if value.get("synthetic") is not True:
        raise ValueError("this runner accepts only explicitly synthetic teaching data")
    sources = {source["id"]: source for source in value["sources"]}
    cases = value["cases"]
    if len(sources) != len(value["sources"]) or len(
        {case["id"] for case in cases}
    ) != len(cases):
        raise ValueError("duplicate source or sample ID")
    groups = {}
    for source in sources.values():
        if hashlib.sha256(source["text"].encode()).hexdigest() != source["sha256"]:
            raise ValueError("source hash mismatch")
        groups.setdefault(source["group"], set()).add(source["split"])
    for case in cases:
        if case["split"] not in {"dev", "test"}:
            raise ValueError("invalid evaluation split")
        groups.setdefault(case["group"], set()).add(case["split"])
        refs = case["reference_sources"]
        if bool(refs) == case["expected_refusal"]:
            raise ValueError("reference/refusal mismatch")
        for reference in refs:
            source = sources[reference]
            if (
                source["split"] != case["split"]
                or source["kb"] not in case["allowed_kbs"]
            ):
                raise ValueError("reference split or authorization mismatch")
        if any(
            not any(term in sources[ref]["text"] for ref in refs)
            for term in case["answer_terms"]
        ):
            raise ValueError("reference answer is not supported by source")
    if any(len(splits) != 1 for splits in groups.values()):
        raise ValueError("source group crosses split")
    return value
