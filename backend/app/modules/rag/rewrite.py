"""Resolve referents from authorized history with one bounded model call."""

import json
import re
from dataclasses import dataclass

from app.modules.providers.base import Provider
from app.modules.providers.schemas import LLMMessage, LLMUsage

from .generation import collect_completion
from .prompts import _valid_text, build_rewrite_prompt, prepare_history
from .schemas import RAGError


@dataclass(frozen=True)
class RewriteResult:
    query: str
    needs_clarification: bool
    used_model: bool
    usage: LLMUsage | None = None


def needs_context(question: str) -> bool:
    return bool(
        re.search(
            r"它|他们|她们|这个|那个|这项|那项|上述|前面|刚才|该产品|该服务|"
            r"^(?:那|还有|然后|支持|可以|能否|需要多久|多少钱|怎么办)",
            question.strip(),
        )
    )


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field")
        result[key] = value
    return result


async def rewrite_query(
    provider: Provider, question: str, history: list[LLMMessage], *, max_tokens: int = 128
) -> RewriteResult:
    if not _valid_text(question) or not 1 <= len(question.strip()) <= 2000:
        raise RAGError("QUESTION_INVALID")
    prepared = prepare_history(history)
    dependent = needs_context(question)
    if not prepared:
        return RewriteResult(question, dependent, False)
    try:
        messages = build_rewrite_prompt(question, prepared)
    except RAGError as error:
        if error.code != "CONTEXT_LIMIT":
            raise
        return RewriteResult(question, dependent, False)
    completion = await collect_completion(provider, messages, max_tokens=max_tokens)
    fallback = RewriteResult(question, dependent, True, completion.usage)
    try:
        data = json.loads(completion.text, object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or set(data) != {"query", "needs_clarification"}:
            return fallback
        query, clarify = data["query"], data["needs_clarification"]
        if type(clarify) is not bool or not _valid_text(query):
            return fallback
        if clarify:
            return RewriteResult(question, True, True, completion.usage)
        if not 1 <= len(query.strip()) <= 2000 or needs_context(query):
            return fallback
        return RewriteResult(query.strip(), False, True, completion.usage)
    except (ValueError, TypeError, RecursionError):
        return fallback
