import asyncio
from contextlib import aclosing

import pytest

from .fixtures.cloud_events import DONE, cloud_server, event

pytestmark = pytest.mark.anyio


async def collect(provider, messages):
    async with aclosing(provider.stream(messages, max_tokens=32, temperature=0.3)) as stream:
        return [delta async for delta in stream]


async def test_fragmented_utf8_sse_usage_and_request_contract(make_provider, messages):
    wire = (
        b": heartbeat\r\n\r\n"
        + event(delta={"role": "assistant"})
        + event("你好，")
        + event("世界🌍")
        + event(finish="stop")
        + event(usage={"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": 11})
        + DONE
        + DONE
    )
    parts = [wire[i : i + 2] for i in range(0, len(wire), 2)]
    async with cloud_server(parts) as (url, requests, _):
        result = await collect(make_provider(url), messages)
    assert "".join(delta.text for delta in result) == "你好，世界🌍"
    assert [delta.finish_reason for delta in result if delta.finish_reason] == ["stop"]
    assert result[-1].usage.model_dump() == {
        "prompt_tokens": 7,
        "completion_tokens": 4,
        "total_tokens": 11,
    }
    assert len(requests) == 1
    line, headers, body = requests[0]
    assert line == "POST /v1/chat/completions HTTP/1.1"
    assert headers["Authorization"] == "Bearer fake-secret-never-log"
    assert body == {
        "model": "fake-model",
        "messages": [{"role": "user", "content": "你好"}],
        "stream": True,
        "max_tokens": 32,
        "temperature": 0.3,
    }


@pytest.mark.parametrize(
    "reason,text", [("stop", "完成"), ("length", "截断"), ("content_filter", "")]
)
async def test_finish_reason_and_missing_usage_remain_explicit(
    make_provider, messages, reason, text
):
    async with cloud_server([event(text), event(finish=reason), DONE]) as (url, _, _):
        result = await collect(make_provider(url), messages)
    assert result[-1].finish_reason == reason
    assert result[-1].usage is None
    assert sum(delta.finish_reason is not None for delta in result) == 1


async def test_no_completion_until_done_even_after_upstream_finish(
    make_provider, messages, provider_api
):
    async with cloud_server([event("部分"), event(finish="stop")]) as (url, requests, _):
        received = []
        with pytest.raises(provider_api["errors"].ProviderError) as error:
            async for delta in make_provider(url).stream(messages, max_tokens=16, temperature=0):
                received.append(delta)
    assert "".join(delta.text for delta in received) == "部分"
    assert not any(delta.finish_reason for delta in received)
    assert error.value.code == "PROVIDER_STREAM_INTERRUPTED"
    assert len(requests) == 1


async def test_consumer_close_releases_upstream_immediately(make_provider, messages):
    async with cloud_server([event("开头")], hold=True) as (url, requests, closed):
        async with aclosing(
            make_provider(url).stream(messages, max_tokens=16, temperature=0)
        ) as stream:
            assert (await anext(stream)).text == "开头"
        await asyncio.wait_for(closed.wait(), 1)
        assert len(requests) == 1


async def test_cancel_pending_read_releases_upstream(make_provider, messages):
    async with cloud_server([event("开头")], hold=True) as (url, requests, closed):
        async with aclosing(
            make_provider(url).stream(messages, max_tokens=16, temperature=0)
        ) as stream:
            await anext(stream)
            task = asyncio.create_task(anext(stream))
            await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        await asyncio.wait_for(closed.wait(), 1)
        assert len(requests) == 1


async def test_mock_is_deterministic_labelled_and_has_no_fake_usage(provider_api, messages):
    settings = provider_api["config"].ModelSettings(_env_file=None, model_provider="mock")
    provider = provider_api["factory"].create_provider(settings)
    first = await collect(provider, messages)
    second = await collect(provider, messages)
    assert first == second
    assert "Mock" in "".join(delta.text for delta in first)
    assert first[-1].finish_reason == "stop"
    assert first[-1].usage is None


async def test_multiline_data_and_reasoning_fields_do_not_leak(make_provider, messages):
    wire = (
        b'data: {"choices":\n'
        b'data: [{"delta":{"content":"visible","reasoning_content":"hidden"},'
        b'"finish_reason":null}]}\n\n'
    )
    async with cloud_server([wire, event(finish="stop"), DONE]) as (url, _, _):
        result = await collect(make_provider(url), messages)
    assert "".join(delta.text for delta in result) == "visible"


async def test_partial_usage_preserves_missing_counts(make_provider, messages):
    async with cloud_server(
        [event("hi"), event(finish="stop"), event(usage={"prompt_tokens": 2}), DONE]
    ) as (url, _, _):
        result = await collect(make_provider(url), messages)
    assert result[-1].usage.model_dump() == {
        "prompt_tokens": 2,
        "completion_tokens": None,
        "total_tokens": None,
    }


async def test_smoke_makes_one_bounded_call_and_returns_only_summary(provider_api):
    import importlib

    try:
        smoke = importlib.import_module("app.modules.providers.smoke")
    except ModuleNotFoundError:
        pytest.fail("Controlled smoke entry point is missing")
    async with cloud_server([event("你好"), event(finish="stop"), DONE]) as (url, requests, _):
        settings = provider_api["config"].ModelSettings(
            _env_file=None,
            model_provider="cloud",
            model_base_url=url,
            model_id="fake-model",
            model_allowed_ids=["fake-model"],
            model_api_key="fake-secret",
        )
        summary = await smoke.run_smoke(settings)
    assert len(requests) == 1
    assert requests[0][2]["max_tokens"] == 64
    assert summary["finish_reason"] == "stop"
    assert summary["usage"] is None
    assert summary["text_characters"] == 2
    assert summary["elapsed_seconds"] >= 0
    assert "fake-secret" not in str(summary)
