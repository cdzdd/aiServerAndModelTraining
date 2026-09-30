"""Metrics with explicit denominators; absent generation remains unknown."""

from statistics import mean


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _percentile(values, percentile):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * percentile
    lower = int(index)
    fraction = index - lower
    return values[lower] + fraction * (values[min(lower + 1, len(values) - 1)] - values[lower])


def summarize(rows, k=5):
    if k < 1:
        raise ValueError("k must be positive")
    answerable = [row for row in rows if row["reference_sources"]]
    recalls, reciprocals = [], []
    for row in answerable:
        references = set(row["reference_sources"])
        ranked = list(dict.fromkeys(row["retrieved_sources"]))[:k]
        recalls.append(len(references.intersection(ranked)) / len(references))
        reciprocals.append(
            next(
                (1 / rank for rank, source in enumerate(ranked, 1) if source in references),
                0,
            )
        )
    generated = [row for row in rows if row["answer_status"] is not None]
    citations = [
        (source in row["reference_sources"], mapped)
        for row in generated
        for source, mapped in zip(row["citation_sources"], row["citation_mapped"], strict=True)
    ]
    false_answers = sum(
        row["expected_refusal"] and row["answer_status"] == "answered" for row in generated
    )
    false_refusals = sum(
        not row["expected_refusal"] and row["answer_status"] != "answered" for row in generated
    )
    return {
        "samples": len(rows),
        "retrieval_denominator": len(answerable),
        "recall_at_k": mean(recalls) if recalls else None,
        "mrr": mean(reciprocals) if reciprocals else None,
        "citation_denominator": len(citations),
        "citation_correctness": _ratio(sum(correct for correct, _ in citations), len(citations)),
        "citation_mapping": _ratio(sum(mapped for _, mapped in citations), len(citations)),
        "refusal_denominator": len(generated),
        "refusal_accuracy": _ratio(
            sum(
                (row["expected_refusal"] and row["answer_status"] in {"no_answer", "clarify"})
                or (not row["expected_refusal"] and row["answer_status"] == "answered")
                for row in generated
            ),
            len(generated),
        ),
        "false_answer_count": false_answers,
        "false_refusal_count": false_refusals,
        "permission_leaks": sum(len(row["unauthorized_sources"]) for row in rows),
        "error_count": sum(bool(row.get("error")) for row in rows),
        "p50_latency_ms": _percentile([row["latency_ms"] for row in rows], 0.5),
        "p95_latency_ms": _percentile([row["latency_ms"] for row in rows], 0.95),
    }
