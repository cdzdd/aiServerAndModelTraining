import asyncio
import json

import pytest

from app.modules.providers.errors import ProviderError
from app.modules.providers.schemas import LLMDelta, LLMMessage, LLMUsage
from app.modules.rag.generation import collect_completion
from app.modules.rag.rewrite import rewrite_query
from app.modules.rag.schemas import RAGError


class RewriteProvider:
    def __init__(self, steps):
        self.steps = steps
        self.calls = []
        self.closed = False

    async def stream(self, messages, *, max_tokens, temperature):
        self.calls.append((messages, max_tokens, temperature))
        try:
            for step in self.steps:
                if isinstance(step, BaseException):
                    raise step
                yield step
        finally:
            self.closed = True


def response(text):
    return RewriteProvider([LLMDelta(text=text), LLMDelta(finish_reason="stop")])


def history():
    return [
        LLMMessage(role="user", content="介绍一下产品 A"),
        LLMMessage(role="assistant", content="产品 A 是服务产品。"),
    ]


def test_pronoun_rewrite_resolves_entity_and_uses_one_bounded_call():
    provider = response('{"query":"产品 A 支持退款吗？","needs_clarification":false}')
    result = asyncio.run(rewrite_query(provider, "它支持退款吗？", history()))
    assert result.query == "产品 A 支持退款吗？"
    assert result.needs_clarification is False
    assert result.used_model is True
    assert len(provider.calls) == 1
    assert provider.calls[0][1:] == (128, 0)
    assert provider.closed


def test_no_history_preserves_independent_question_without_model_call():
    provider = response("invalid")
    result = asyncio.run(rewrite_query(provider, "产品 A 支持退款吗？", []))
    assert result.query == "产品 A 支持退款吗？"
    assert not result.needs_clarification
    assert not result.used_model
    assert provider.calls == []


def test_pronoun_without_history_requires_clarification_without_call():
    provider = response("invalid")
    result = asyncio.run(rewrite_query(provider, "它支持退款吗？", []))
    assert result.needs_clarification
    assert not result.used_model
    assert provider.calls == []


@pytest.mark.parametrize(
    "raw",
    [
        "not JSON",
        '{"query":"机密库退款政策","needs_clarification":false,"kb_ids":["admin"]}',
        '{"query":"产品 A","needs_clarification":"false"}',
        '{"query":"产品 A","query":"产品 B","needs_clarification":false}',
        '{"query":"","needs_clarification":false}',
        '{"query":"bad\\ud800","needs_clarification":false}',
        '```json\n{"query":"产品 A","needs_clarification":false}\n```',
    ],
)
def test_invalid_rewrite_cannot_invent_a_standalone_query(raw):
    provider = response(raw)
    result = asyncio.run(rewrite_query(provider, "它支持退款吗？", history()))
    assert result.needs_clarification
    assert result.query == "它支持退款吗？"
    assert result.used_model


def test_invalid_rewrite_falls_back_only_to_independent_original():
    provider = response("not JSON")
    result = asyncio.run(rewrite_query(provider, "产品 B 支持退款吗？", history()))
    assert result.query == "产品 B 支持退款吗？"
    assert not result.needs_clarification
    assert result.used_model


def test_explicit_model_uncertainty_remains_clarify():
    result = asyncio.run(
        rewrite_query(
            response(json.dumps({"query": "", "needs_clarification": True})),
            "它支持退款吗？",
            history(),
        )
    )
    assert result.needs_clarification


@pytest.mark.parametrize("question", ["bad\x00text", "bad\ud800"])
def test_invalid_unicode_or_nul_question_rejected_before_call(question):
    provider = response("invalid")
    with pytest.raises(RAGError, match="QUESTION_INVALID"):
        asyncio.run(rewrite_query(provider, question, []))
    assert not provider.calls


def test_provider_failure_is_not_hidden_as_rewrite_fallback():
    provider = RewriteProvider([ProviderError("PROVIDER_AUTH_FAILED")])
    with pytest.raises(RAGError, match="PROVIDER_AUTH_FAILED"):
        asyncio.run(rewrite_query(provider, "产品 B 支持退款吗？", history()))
    assert provider.closed
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    ("steps", "code"),
    [
        ([LLMDelta(text="half")], "PROVIDER_STREAM_INTERRUPTED"),
        (
            [LLMDelta(text="half"), LLMDelta(finish_reason="length")],
            "PROVIDER_UNSUPPORTED_RESPONSE",
        ),
        (
            [LLMDelta(text="half"), LLMDelta(finish_reason="content_filter")],
            "PROVIDER_UNSUPPORTED_RESPONSE",
        ),
        ([LLMDelta(finish_reason="stop")], "PROVIDER_EMPTY_RESPONSE"),
        ([LLMDelta(text="a" * 8193)], "RAG_INVALID_OUTPUT"),
        (
            [LLMDelta(text="a"), LLMDelta(finish_reason="stop"), LLMDelta(text="b")],
            "PROVIDER_PROTOCOL_ERROR",
        ),
        (
            [LLMDelta(text="a"), LLMDelta(finish_reason="stop"), LLMDelta(finish_reason="stop")],
            "PROVIDER_PROTOCOL_ERROR",
        ),
    ],
)
def test_collection_rejects_incomplete_or_unbounded_output_and_closes(steps, code):
    provider = RewriteProvider(steps)
    with pytest.raises(RAGError, match=code):
        asyncio.run(
            collect_completion(provider, [LLMMessage(role="user", content="q")], max_tokens=128)
        )
    assert provider.closed
    assert len(provider.calls) == 1


def test_collection_returns_only_actual_usage():
    usage = LLMUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13)
    provider = RewriteProvider([LLMDelta(text="ok"), LLMDelta(finish_reason="stop", usage=usage)])
    result = asyncio.run(
        collect_completion(provider, [LLMMessage(role="user", content="q")], max_tokens=128)
    )
    assert result.text == "ok"
    assert result.usage == usage
    assert provider.closed


def test_collection_propagates_cancellation_and_closes():
    provider = RewriteProvider([LLMDelta(text="half"), asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            collect_completion(provider, [LLMMessage(role="user", content="q")], max_tokens=128)
        )
    assert provider.closed
