"""Bounded, extractive RAG; no text is emitted before current-source validation."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from uuid import UUID

from app.core.request_context import log_failure
from app.modules.auth.schemas import Actor
from app.modules.providers.errors import MESSAGES as PROVIDER_MESSAGES
from app.modules.providers.errors import ProviderError
from app.modules.providers.factory import create_provider
from app.modules.providers.schemas import LLMMessage, LLMUsage
from app.modules.rag.citations import render_answer, validate_selection
from app.modules.rag.generation import collect_completion
from app.modules.rag.intent import classify_intent
from app.modules.rag.prompts import PROMPT_VERSION, build_answer_prompt, prepare_history
from app.modules.rag.rewrite import rewrite_query
from app.modules.rag.schemas import AnswerEvent, RAGError
from app.modules.retrieval.embedding import EmbeddingError
from app.modules.retrieval.schemas import RetrievalError

logger = logging.getLogger(__name__)

NO_ANSWER = "当前可访问资料中未找到足够依据，请补充具体问题或咨询人工客服。"
CLARIFY = "请明确您咨询的对象和事项，以便查找相关资料。"
SHORTEN = "请缩短问题或一次只问一个事项，以便查找相关资料。"
INTENT_REPLIES = {
    "handoff": "您可以申请人工客服，请使用转人工入口发起申请。",
    "complaint": "理解您对这次服务的不满，您可以申请人工客服进一步说明投诉事项。",
    "other": "您好，我可以根据您有权访问的知识资料回答问题，请告诉我您想了解的事项。",
}
ERROR_MESSAGES = {
    **PROVIDER_MESSAGES,
    "QUESTION_INVALID": "问题应为1至2000个有效字符。",
    "HISTORY_INVALID": "对话历史格式无效，请重新发起提问。",
    "RAG_TIMEOUT": "回答处理超时，请稍后重试。",
    "RAG_INVALID_OUTPUT": "模型响应无效，请稍后重试。",
    "SOURCE_CHANGED": "资料或访问权限已发生变化，请重新提问。",
    "MODEL_INDEX_MISMATCH": "知识索引需要更新，请联系管理员。",
    "MODEL_UNAVAILABLE": "知识检索模型暂不可用，请稍后重试。",
    "MODEL_INTEGRITY": "知识检索模型不可用，请联系管理员。",
    "ENCODE_FAILED": "知识检索暂不可用，请稍后重试。",
    "RAG_UNAVAILABLE": "回答服务暂不可用，请稍后重试。",
}


def _error(code: str) -> AnswerEvent:
    if code not in ERROR_MESSAGES:
        code = "RAG_UNAVAILABLE"
    log_failure(logger, "rag_failure", code, prompt_version=PROMPT_VERSION)
    return AnswerEvent(type="error", payload={"code": code, "message": ERROR_MESSAGES[code]})


def _usage(stages: list[LLMUsage | None]) -> dict | None:
    if not stages or any(stage is None for stage in stages):
        return None
    result = {}
    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
        values = [getattr(stage, field) for stage in stages]
        result[field] = None if any(value is None for value in values) else sum(values)
    return result


def _events(
    text, *, status="no_answer", evidence="none", intent="knowledge", citations=(), usages=()
) -> list[AnswerEvent]:
    return [
        AnswerEvent(type="delta", payload={"text": text}),
        AnswerEvent(
            type="citations",
            payload={"items": [citation.model_dump(mode="json") for citation in citations]},
        ),
        AnswerEvent(
            type="done",
            payload={
                "answer_status": status,
                "evidence_level": evidence,
                "intent": intent,
                "usage": _usage(list(usages)),
            },
        ),
    ]


def _question(value: str) -> str:
    if not isinstance(value, str) or "\0" in value:
        raise RAGError("QUESTION_INVALID")
    value = value.strip()
    if not 1 <= len(value) <= 2000:
        raise RAGError("QUESTION_INVALID")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise RAGError("QUESTION_INVALID") from None
    return value


class RAGService:
    def __init__(self, retriever, validate_hits, provider, *, timeout_seconds=60):
        self.retriever = retriever
        self.validate_hits = validate_hits
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    async def stream_answer(
        self, actor: Actor, kb_ids: list[UUID], question: str, history: list[LLMMessage]
    ) -> AsyncIterator[AnswerEvent]:
        try:
            # Exit the deadline before yielding: the consumer owns downstream pacing.
            async with asyncio.timeout(self.timeout_seconds):
                events = await self._prepare(actor, list(kb_ids), question, history)
        except TimeoutError:
            events = [_error("RAG_TIMEOUT")]
        except (RAGError, ProviderError, RetrievalError, EmbeddingError) as exc:
            events = [_error(exc.code)]
        except Exception:
            events = [_error("RAG_UNAVAILABLE")]
        # CancelledError/GeneratorExit are intentionally never converted into success.
        for event in events:
            yield event

    async def _prepare(self, actor, kb_ids, question, history):
        question = _question(question)
        history = prepare_history(history)
        intent = classify_intent(question)
        if intent != "knowledge":
            return _events(INTENT_REPLIES[intent], intent=intent)

        usages = []
        try:
            rewritten = await rewrite_query(self.provider, question, history, max_tokens=128)
            if rewritten.used_model:
                usages.append(rewritten.usage)
            if rewritten.needs_clarification:
                return _events(CLARIFY, status="clarify", usages=usages)
            hits = await self.retriever(actor, kb_ids, rewritten.query, top_k=5)
            if not hits:
                return _events(NO_ANSWER, usages=usages)
            messages, prompt_hits = build_answer_prompt(
                question, hits, retrieval_query=rewritten.query
            )
            if not prompt_hits:
                return _events(NO_ANSWER, usages=usages)
        except (RAGError, EmbeddingError, RetrievalError) as exc:
            if exc.code not in {"CONTEXT_LIMIT", "TOKEN_LIMIT"}:
                raise
            return _events(SHORTEN, status="clarify", usages=usages)

        completion = await collect_completion(
            self.provider, messages, max_tokens=384 if rewritten.used_model else 512
        )
        usages.append(completion.usage)
        try:
            status, citations, used_hits = validate_selection(completion.text, prompt_hits)
        except RAGError as exc:
            if exc.code != "INVALID_CITATION":
                raise
            log_failure(logger, "rag_refusal", "INVALID_CITATION", prompt_version=PROMPT_VERSION)
            return _events(NO_ANSWER, usages=usages)
        if status == "no_answer":
            return _events(NO_ANSWER, usages=usages)
        if status == "clarify":
            return _events(CLARIFY, status="clarify", evidence="limited", usages=usages)
        if not await self.validate_hits(actor, kb_ids, used_hits):
            raise RAGError("SOURCE_CHANGED")
        return _events(
            render_answer(citations),
            status="answered",
            evidence="sufficient",
            citations=citations,
            usages=usages,
        )


async def stream_answer(
    actor: Actor, kb_ids: list[UUID], question: str, history: list[LLMMessage]
) -> AsyncIterator[AnswerEvent]:
    from app.modules.retrieval.service import search, validate_hits

    try:
        provider = create_provider()
    except ProviderError as exc:
        yield _error(exc.code)
        return
    service = RAGService(search, validate_hits, provider)
    async with aclosing(service.stream_answer(actor, kb_ids, question, history)) as stream:
        async for event in stream:
            yield event
