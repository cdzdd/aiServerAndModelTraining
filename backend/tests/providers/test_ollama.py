import asyncio
import json
import traceback
from contextlib import aclosing

import pytest

from .fixtures.cloud_events import cloud_server
from .test_cloud_stream import collect

pytestmark = pytest.mark.anyio


def frame(text="", *, done=False, reason=None, **fields):
    payload = {"message": {"role": "assistant", "content": text}, "done": done}
    if reason is not None:
        payload["done_reason"] = reason
    payload.update(fields)
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode()


@pytest.fixture
def make_ollama(make_provider):
    def make(url, **overrides):
        overrides.setdefault("ollama_num_ctx", 4096)
        return make_provider(
            url.removesuffix("/v1"), model_provider="ollama", model_api_key="", **overrides
        )

    return make


async def test_fragmented_ndjson_utf8_usage_and_request(make_ollama, messages):
    wire = (
        frame("你好，")
        + frame("世界🌍", message={"content": "世界🌍", "thinking": "hidden"})
        + frame("！", done=True, reason="stop", prompt_eval_count=7, eval_count=4)
        + frame(done=True, reason="stop")
    )
    parts = [wire[i : i + 2] for i in range(0, len(wire), 2)]
    async with cloud_server(parts, content_type="application/x-ndjson") as (url, requests, _):
        result = await collect(make_ollama(url), messages)
    assert "".join(delta.text for delta in result) == "你好，世界🌍！"
    assert [d.finish_reason for d in result if d.finish_reason] == ["stop"]
    assert result[-1].text == ""
    assert result[-1].usage.model_dump() == {
        "prompt_tokens": 7,
        "completion_tokens": 4,
        "total_tokens": None,
    }
    line, headers, body = requests[0]
    assert line == "POST /api/chat HTTP/1.1"
    assert "Authorization" not in headers
    assert body == {
        "model": "fake-model",
        "messages": [{"role": "user", "content": "你好"}],
        "stream": True,
        "truncate": False,
        "shift": False,
        "options": {"num_predict": 32, "temperature": 0.3, "num_ctx": 4096},
    }
    assert len(requests) == 1


@pytest.mark.parametrize("reason", ["stop", "length"])
async def test_completion_reason_without_usage(make_ollama, messages, reason):
    async with cloud_server(
        [frame("文本", done=True, reason=reason).rstrip(b"\n")],
        content_type="application/x-ndjson; charset=utf-8",
    ) as (url, _, _):
        result = await collect(make_ollama(url), messages)
    assert result[-1].finish_reason == reason
    assert result[-1].usage is None


async def test_partial_usage_is_not_filled_in(make_ollama, messages):
    async with cloud_server(
        [frame("文本", done=True, reason="stop", prompt_eval_count=0)],
        content_type="application/x-ndjson",
    ) as (url, _, _):
        result = await collect(make_ollama(url), messages)
    assert result[-1].usage.model_dump() == {
        "prompt_tokens": 0,
        "completion_tokens": None,
        "total_tokens": None,
    }


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "PROVIDER_BAD_REQUEST"),
        (401, "PROVIDER_AUTH_FAILED"),
        (403, "PROVIDER_AUTH_FAILED"),
        (404, "PROVIDER_UNAVAILABLE"),
        (429, "PROVIDER_RATE_LIMITED"),
        (500, "PROVIDER_UNAVAILABLE"),
        (503, "PROVIDER_UNAVAILABLE"),
        (302, "PROVIDER_BAD_REQUEST"),
    ],
)
async def test_http_failures_are_sanitized_no_retry(make_ollama, messages, status, code):
    from app.modules.providers.errors import ProviderError

    async with cloud_server(
        [b'{"error":"private-host.local secret body"}'],
        status=status,
    ) as (url, requests, _):
        with pytest.raises(ProviderError) as error:
            await collect(make_ollama(url), messages)
    assert error.value.code == code
    visible = "".join(traceback.format_exception(error.value))
    assert "private-host" not in visible
    assert "secret body" not in visible
    assert len(requests) == 1


@pytest.mark.parametrize(
    "parts,code",
    [
        ([frame("部分")], "PROVIDER_STREAM_INTERRUPTED"),
        ([frame(done=True, reason="stop")], "PROVIDER_EMPTY_RESPONSE"),
        ([frame("  ", done=True, reason="stop")], "PROVIDER_EMPTY_RESPONSE"),
        ([frame("文本", done=True)], "PROVIDER_PROTOCOL_ERROR"),
        ([frame("文本", reason="stop")], "PROVIDER_PROTOCOL_ERROR"),
        ([frame("文本", done="true", reason="stop")], "PROVIDER_PROTOCOL_ERROR"),
        ([b"{bad secret body}\n"], "PROVIDER_PROTOCOL_ERROR"),
        ([b"[]\n"], "PROVIDER_PROTOCOL_ERROR"),
        ([b'{"done":false}\n'], "PROVIDER_PROTOCOL_ERROR"),
        ([frame(message={"content": 42})], "PROVIDER_PROTOCOL_ERROR"),
        ([frame("文本", done=True, reason="stop", eval_count=-1)], "PROVIDER_PROTOCOL_ERROR"),
        ([frame("文本", done=True, reason="stop", eval_count=True)], "PROVIDER_PROTOCOL_ERROR"),
        ([frame("文本", done=True, reason="stop", eval_count="1")], "PROVIDER_PROTOCOL_ERROR"),
        ([frame(message={"tool_calls": [{"function": {}}]})], "PROVIDER_UNSUPPORTED_RESPONSE"),
        ([frame("文本", done=True, reason="unknown")], "PROVIDER_UNSUPPORTED_RESPONSE"),
        ([frame("部分"), b'{"error":"private-host.local secret body"}\n'], "PROVIDER_UNAVAILABLE"),
        pytest.param(
            [b'{"message":{"content":"\\ud800"},"done":true,"done_reason":"stop"}\n'],
            "PROVIDER_PROTOCOL_ERROR",
            id="unpaired-surrogate",
        ),
        pytest.param(
            [
                b'{"extra":' + b"[" * 10000 + b"0" + b"]" * 10000
                + b',"message":{"content":"ok"},"done":true,"done_reason":"stop"}\n'
            ],
            "PROVIDER_PROTOCOL_ERROR",
            id="deeply-nested-json",
        ),
        ([b"x" * 65537], "PROVIDER_PROTOCOL_ERROR"),
        ([b'{"message":{"content":"\xff"},"done":false}\n'], "PROVIDER_PROTOCOL_ERROR"),
    ],
)
async def test_invalid_stream_never_emits_success(make_ollama, messages, parts, code):
    from app.modules.providers.errors import ProviderError

    async with cloud_server(parts, content_type="application/x-ndjson") as (url, requests, _):
        received = []
        with pytest.raises(ProviderError) as error:
            async for delta in make_ollama(url).stream(messages, max_tokens=16, temperature=0):
                received.append(delta)
    assert error.value.code == code
    assert not any(delta.finish_reason for delta in received)
    assert "secret body" not in "".join(traceback.format_exception(error.value))
    assert len(requests) == 1


async def test_content_type_rejected(make_ollama, messages):
    from app.modules.providers.errors import ProviderError

    async with cloud_server([frame("hi", done=True, reason="stop")]) as (url, _, _):
        with pytest.raises(ProviderError, match="模型响应格式无效"):
            await collect(make_ollama(url), messages)


async def test_close_and_terminal_release_socket(make_ollama, messages):
    for wire in [frame("开头"), frame("完成", done=True, reason="stop")]:
        async with cloud_server(
            [wire],
            content_type="application/x-ndjson",
            hold=True,
        ) as (url, requests, closed):
            async with aclosing(
                make_ollama(url).stream(messages, max_tokens=16, temperature=0)
            ) as stream:
                assert (await anext(stream)).text
                if b'"done": true' in wire:
                    terminal = await anext(stream)
                    assert terminal.finish_reason == "stop"
                    await asyncio.wait_for(closed.wait(), 1)
            await asyncio.wait_for(closed.wait(), 1)
            assert len(requests) == 1


async def test_cancel_pending_read_releases_socket(make_ollama, messages):
    async with cloud_server(
        [frame("开头")],
        content_type="application/x-ndjson",
        hold=True,
    ) as (url, requests, closed):
        async with aclosing(
            make_ollama(url).stream(messages, max_tokens=16, temperature=0)
        ) as stream:
            await anext(stream)
            task = asyncio.create_task(anext(stream))
            await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        await asyncio.wait_for(closed.wait(), 1)
        assert len(requests) == 1


@pytest.mark.parametrize("delay_headers,parts", [(1, []), (0, [frame("部分")])])
async def test_timeout_closes_socket(make_ollama, messages, delay_headers, parts):
    from app.modules.providers.errors import ProviderError

    async with cloud_server(
        parts,
        content_type="application/x-ndjson",
        hold=True,
        delay_headers=delay_headers,
    ) as (url, requests, closed):
        with pytest.raises(ProviderError) as error:
            await collect(make_ollama(url), messages)
        if not delay_headers:
            await asyncio.wait_for(closed.wait(), 1)
        assert len(requests) == 1
    assert error.value.code == "PROVIDER_TIMEOUT"


async def test_connect_failure_never_falls_back(make_ollama, messages, monkeypatch):
    import httpx2

    from app.modules.providers.errors import ProviderError

    async def offline(*args, **kwargs):
        raise httpx2.ConnectError("private-host.local secret body")

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", offline)
    with pytest.raises(ProviderError) as error:
        await collect(make_ollama("http://127.0.0.1:1"), messages)
    assert error.value.code == "PROVIDER_UNAVAILABLE"
    assert "private-host" not in "".join(traceback.format_exception(error.value))


async def test_rag_collector_accepts_stop_and_rejects_length(make_ollama, messages):
    from app.modules.rag.generation import collect_completion
    from app.modules.rag.schemas import RAGError

    for reason in ["stop", "length"]:
        async with cloud_server(
            [frame("知识文字", done=True, reason=reason)],
            content_type="application/x-ndjson",
        ) as (url, _, _):
            if reason == "stop":
                result = await collect_completion(make_ollama(url), messages, max_tokens=32)
                assert result.text == "知识文字"
            else:
                with pytest.raises(RAGError) as error:
                    await collect_completion(make_ollama(url), messages, max_tokens=32)
                assert error.value.code == "PROVIDER_UNSUPPORTED_RESPONSE"


async def test_explicit_thinking_and_context_config(make_ollama, messages):
    async with cloud_server(
        [frame("文本", done=True, reason="stop")],
        content_type="application/x-ndjson",
    ) as (url, requests, _):
        await collect(make_ollama(url, model_disable_thinking=True, ollama_num_ctx=2048), messages)
    assert requests[0][2]["think"] is False
    assert requests[0][2]["options"]["num_ctx"] == 2048
