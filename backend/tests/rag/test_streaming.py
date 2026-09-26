import asyncio
import json

import pytest
from service_helpers import (
    ACTOR,
    KB_IDS,
    QUOTE,
    ScriptedProvider,
    Sources,
    answer,
    collect,
    complete,
    hit,
    text_of,
)

from app.modules.providers.errors import ProviderError
from app.modules.providers.schemas import LLMDelta, LLMMessage, LLMUsage
from app.modules.rag.service import RAGService


def test_answer_emits_only_selected_verified_quotes_and_current_source_metadata():
    source, unused = hit(), hit("其他来源")
    sources = Sources([source, unused])
    provider = ScriptedProvider(complete(answer()))
    events = collect(RAGService(sources.search, sources.validate, provider))
    assert [event.type for event in events] == ["delta", "citations", "done"]
    assert QUOTE in text_of(events)
    assert '"selections"' not in text_of(events)
    assert "其他来源" not in text_of(events)
    item = events[1].payload["items"][0]
    assert item["source_id"] == str(source.source_id)
    assert item["quote"] == QUOTE
    assert item["revision_id"] == str(source.revision_id)
    assert sources.checks == [(ACTOR, KB_IDS, [source])]
    assert events[-1].payload["answer_status"] == "answered"
    assert events[-1].payload["evidence_level"] == "sufficient"
    assert provider.calls[0][1] == 512
    assert provider.closed == 1


def test_revoked_or_changed_source_never_emits_old_text():
    sources = Sources([hit()], valid=False)
    provider = ScriptedProvider(complete(answer()))
    events = collect(RAGService(sources.search, sources.validate, provider))
    assert [event.type for event in events] == ["error"]
    assert events[0].payload["code"] == "SOURCE_CHANGED"
    assert QUOTE not in str(events)


@pytest.mark.parametrize(
    "failure",
    [
        ProviderError("PROVIDER_TIMEOUT"),
        ProviderError("PROVIDER_AUTH_FAILED"),
        RuntimeError("SECRET-INTERNAL-DETAIL"),
    ],
)
def test_failure_after_partial_json_emits_one_safe_error_without_retry(failure):
    sources = Sources([hit()])
    provider = ScriptedProvider([LLMDelta(text='{"status":"answered"'), failure])
    events = collect(RAGService(sources.search, sources.validate, provider))
    assert [event.type for event in events] == ["error"]
    assert "SECRET-INTERNAL-DETAIL" not in str(events)
    assert "answered" not in str(events)
    assert len(provider.calls) == provider.closed == 1


@pytest.mark.parametrize("reason", ["length", "content_filter"])
def test_incomplete_completion_is_not_parsed_or_emitted(reason):
    sources = Sources([hit()])
    provider = ScriptedProvider([LLMDelta(text=answer()), LLMDelta(finish_reason=reason)])
    events = collect(RAGService(sources.search, sources.validate, provider))
    assert [event.type for event in events] == ["error"]
    assert provider.closed == 1


def test_no_text_is_emitted_while_provider_json_is_incomplete():
    async def run():
        release, started = asyncio.Event(), asyncio.Event()

        class PausedProvider:
            closed = False

            async def stream(self, messages, *, max_tokens, temperature):
                try:
                    yield LLMDelta(text=answer())
                    started.set()
                    await release.wait()
                    yield LLMDelta(finish_reason="stop")
                finally:
                    self.closed = True

        provider, sources = PausedProvider(), Sources([hit()])
        stream = RAGService(sources.search, sources.validate, provider).stream_answer(
            ACTOR, KB_IDS, "图书馆何时开放？", []
        )
        first = asyncio.create_task(anext(stream))
        await asyncio.wait_for(started.wait(), timeout=1)
        assert not first.done()
        assert sources.checks == []
        release.set()
        assert (await first).type == "delta"
        await stream.aclose()
        assert provider.closed

    asyncio.run(run())


def test_cancelled_consumer_closes_provider_and_propagates_cancellation():
    async def run():
        started, closed = asyncio.Event(), asyncio.Event()

        class HangingProvider:
            async def stream(self, messages, *, max_tokens, temperature):
                try:
                    yield LLMDelta(text='{"status":')
                    started.set()
                    await asyncio.Event().wait()
                finally:
                    closed.set()

        sources = Sources([hit()])
        stream = RAGService(sources.search, sources.validate, HangingProvider()).stream_answer(
            ACTOR, KB_IDS, "图书馆何时开放？", []
        )
        first = asyncio.create_task(anext(stream))
        await asyncio.wait_for(started.wait(), timeout=1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert closed.is_set()
        await stream.aclose()

    asyncio.run(run())


def test_one_deadline_covers_rewrite_and_generation_not_a_reset_per_stage():
    sources = Sources([hit()])
    rewrite = json.dumps({"query": "图书馆何时开放？", "needs_clarification": False})
    provider = ScriptedProvider([0.07, *complete(rewrite)], [0.07, *complete(answer())])
    events = collect(
        RAGService(sources.search, sources.validate, provider, timeout_seconds=0.11),
        "它何时开放？",
        [
            LLMMessage(role="user", content="图书馆在哪里？"),
            LLMMessage(role="assistant", content="校内"),
        ],
    )
    assert [event.type for event in events] == ["error"]
    assert events[0].payload["code"] == "RAG_TIMEOUT"
    assert [call[1] for call in provider.calls] == [128, 384]
    assert provider.closed == 2


def test_deadline_includes_source_revalidation():
    sources = Sources([hit()])

    async def slow_validation(actor, kb_ids, hits):
        await asyncio.sleep(1)
        return True

    provider = ScriptedProvider(complete(answer()))
    events = collect(RAGService(sources.search, slow_validation, provider, timeout_seconds=0.02))
    assert [event.type for event in events] == ["error"]
    assert events[0].payload["code"] == "RAG_TIMEOUT"


@pytest.mark.parametrize(
    "second_usage, expected",
    [
        (
            LLMUsage(prompt_tokens=20, completion_tokens=8, total_tokens=28),
            {"prompt_tokens": 30, "completion_tokens": 11, "total_tokens": 41},
        ),
        (
            LLMUsage(completion_tokens=8),
            {"prompt_tokens": None, "completion_tokens": 11, "total_tokens": None},
        ),
        (None, None),
    ],
)
def test_usage_sums_only_known_actual_fields(second_usage, expected):
    sources = Sources([hit()])
    rewrite = json.dumps({"query": "图书馆何时开放？", "needs_clarification": False})
    provider = ScriptedProvider(
        complete(rewrite, LLMUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13)),
        complete(answer(), second_usage),
    )
    events = collect(
        RAGService(sources.search, sources.validate, provider),
        "它何时开放？",
        [
            LLMMessage(role="user", content="图书馆在哪里？"),
            LLMMessage(role="assistant", content="校内"),
        ],
    )
    assert events[-1].payload["usage"] == expected
    assert [call[1] for call in provider.calls] == [128, 384]

