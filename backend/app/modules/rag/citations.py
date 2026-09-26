"""Validate extractive model output against the exact evidence sent to the model."""

import json

from app.modules.rag.schemas import Citation, RAGError
from app.modules.retrieval.schemas import SearchHit


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def validate_selection(
    raw: str, hits: list[SearchHit]
) -> tuple[str, list[Citation], list[SearchHit]]:
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, TypeError, RecursionError):
        raise RAGError("INVALID_CITATION") from None
    if not isinstance(value, dict) or set(value) != {"status", "selections"}:
        raise RAGError("INVALID_CITATION")
    status, selections = value["status"], value["selections"]
    if status not in ("answered", "clarify", "no_answer") or not isinstance(selections, list):
        raise RAGError("INVALID_CITATION")
    if status != "answered":
        if selections:
            raise RAGError("INVALID_CITATION")
        return status, [], []
    if not 1 <= len(selections) <= 3:
        raise RAGError("INVALID_CITATION")
    citations, used_hits, seen = [], [], set()
    for selection in selections:
        if not isinstance(selection, dict) or set(selection) != {"index", "quote"}:
            raise RAGError("INVALID_CITATION")
        index, quote = selection["index"], selection["quote"]
        if type(index) is not int or not 1 <= index <= len(hits) or index in seen:
            raise RAGError("INVALID_CITATION")
        hit = hits[index - 1]
        if not isinstance(quote, str) or not quote.strip() or quote.strip() not in hit.text:
            raise RAGError("INVALID_CITATION")
        citations.append(
            Citation(index=index, quote=quote.strip(), **hit.model_dump(exclude={"score", "text"}))
        )
        used_hits.append(hit)
        seen.add(index)
    if sum(len(citation.quote) for citation in citations) > 800:
        raise RAGError("INVALID_CITATION")
    return status, citations, used_hits


def render_answer(citations: list[Citation]) -> str:
    return "\n\n".join(f"资料原文：{citation.quote} [{citation.index}]" for citation in citations)
