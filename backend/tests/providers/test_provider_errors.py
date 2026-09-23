import logging
import traceback

import pytest

from .fixtures.cloud_events import DONE, cloud_server, event
from .test_cloud_stream import collect

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "PROVIDER_AUTH_FAILED"),
        (403, "PROVIDER_AUTH_FAILED"),
        (429, "PROVIDER_RATE_LIMITED"),
        (500, "PROVIDER_UNAVAILABLE"),
        (503, "PROVIDER_UNAVAILABLE"),
        (400, "PROVIDER_BAD_REQUEST"),
        (302, "PROVIDER_BAD_REQUEST"),
    ],
)
async def test_http_errors_are_mapped_without_credentials_or_retries(
    status, code, make_provider, messages, provider_api, caplog
):
    caplog.set_level(logging.DEBUG)
    async with cloud_server([b"Authorization: Bearer fake-secret-never-log"], status=status) as (
        url,
        requests,
        _,
    ):
        with pytest.raises(provider_api["errors"].ProviderError) as error:
            await collect(make_provider(url), messages)
    assert error.value.code == code
    visible = (
        str(error.value) + repr(error.value) + "".join(traceback.format_exception(error.value))
    )
    assert "fake-secret-never-log" not in visible + caplog.text
    assert "Authorization:" not in visible + caplog.text
    assert len(requests) == 1


@pytest.mark.parametrize(
    "parts,code",
    [
        ([event("部分")], "PROVIDER_STREAM_INTERRUPTED"),
        ([event(finish="stop"), DONE], "PROVIDER_EMPTY_RESPONSE"),
        ([event("  "), event(finish="stop"), DONE], "PROVIDER_EMPTY_RESPONSE"),
        ([event("部分"), DONE], "PROVIDER_PROTOCOL_ERROR"),
        ([b"data: {invalid fake-secret-never-log}\n\n"], "PROVIDER_PROTOCOL_ERROR"),
        ([b'data: {"error":{"message":"fake-secret-never-log"}}\n\n'], "PROVIDER_UNAVAILABLE"),
        (
            [b'data: {"choices":[{"delta":{"content": 42},"finish_reason":null}]}\n\n'],
            "PROVIDER_PROTOCOL_ERROR",
        ),
        ([event(delta={"tool_calls": [{"id": "call-1"}]}), DONE], "PROVIDER_UNSUPPORTED_RESPONSE"),
    ],
)
async def test_incomplete_empty_and_invalid_streams_never_succeed(
    parts, code, make_provider, messages, provider_api, caplog
):
    async with cloud_server(parts) as (url, requests, _):
        with pytest.raises(provider_api["errors"].ProviderError) as error:
            await collect(make_provider(url), messages)
    assert error.value.code == code
    assert "fake-secret-never-log" not in str(error.value) + caplog.text
    assert len(requests) == 1


async def test_read_timeout_after_partial_text_has_no_retry(make_provider, messages, provider_api):
    async with cloud_server([event("部分")], hold=True) as (url, requests, _):
        received = []
        with pytest.raises(provider_api["errors"].ProviderError) as error:
            async for delta in make_provider(url).stream(messages, max_tokens=16, temperature=0):
                received.append(delta)
    assert error.value.code == "PROVIDER_TIMEOUT"
    assert "".join(delta.text for delta in received) == "部分"
    assert len(requests) == 1


async def test_timeout_before_response_headers(make_provider, messages, provider_api):
    async with cloud_server([], delay_headers=1) as (url, requests, _):
        with pytest.raises(provider_api["errors"].ProviderError) as error:
            await collect(make_provider(url), messages)
    assert error.value.code == "PROVIDER_TIMEOUT"
    assert len(requests) == 1


async def test_non_sse_response_rejected(make_provider, messages, provider_api):
    async with cloud_server([b"{}"], content_type="application/json") as (url, _, _):
        with pytest.raises(provider_api["errors"].ProviderError) as error:
            await collect(make_provider(url), messages)
    assert error.value.code == "PROVIDER_PROTOCOL_ERROR"


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_allowed_ids": ["another-model"]},
        {"model_api_key": ""},
        {"model_base_url": "https://user:fake-secret-never-log@example.invalid/v1"},
        {"model_base_url": "https://example.invalid/v1?key=fake-secret-never-log"},
        {"model_base_url": "http://example.invalid/v1"},
        {"model_provider": "arbitrary-plugin"},
    ],
)
async def test_invalid_cloud_configuration_is_rejected(overrides, make_provider):
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as error:
        make_provider("https://example.invalid/v1", **overrides)
    assert "fake-secret-never-log" not in str(error.value)


@pytest.mark.parametrize(
    "max_tokens,temperature", [(0, 0), (513, 0), (16, -0.1), (16, float("nan"))]
)
async def test_invalid_generation_limits_fail_before_request(
    max_tokens, temperature, make_provider, messages, provider_api
):
    async with cloud_server([]) as (url, requests, _):
        with pytest.raises(provider_api["errors"].ProviderError) as error:
            async for _ in make_provider(url).stream(
                messages, max_tokens=max_tokens, temperature=temperature
            ):
                pass
        assert requests == []
    assert error.value.code == "PROVIDER_BAD_REQUEST"


@pytest.mark.parametrize(
    "bad_url",
    ["https://example.invalid:fake-secret-never-log/v1", "https://[fake-secret-never-log/v1"],
)
async def test_malformed_url_validation_never_echoes_configuration(bad_url, make_provider):
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as error:
        make_provider(bad_url)
    assert "fake-secret-never-log" not in str(error.value)


async def test_connect_timeout_is_sanitized(make_provider, messages, provider_api, monkeypatch):
    import httpx2

    async def timeout(*args, **kwargs):
        raise httpx2.ConnectTimeout("Authorization: Bearer fake-secret-never-log")

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", timeout)
    with pytest.raises(provider_api["errors"].ProviderError) as error:
        await collect(make_provider("https://example.invalid/v1"), messages)
    assert error.value.code == "PROVIDER_TIMEOUT"
    assert "fake-secret-never-log" not in "".join(traceback.format_exception(error.value))


async def test_oversized_event_is_rejected(make_provider, messages, provider_api):
    async with cloud_server([b"data: " + b"x" * 65537]) as (url, _, _):
        with pytest.raises(provider_api["errors"].ProviderError) as error:
            await collect(make_provider(url), messages)
    assert error.value.code == "PROVIDER_PROTOCOL_ERROR"


async def test_factory_environment_errors_do_not_echo_secrets(provider_api, monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "cloud")
    monkeypatch.setenv("MODEL_ALLOWED_IDS", "fake-secret-never-log")
    with pytest.raises(provider_api["errors"].ProviderError) as error:
        provider_api["factory"].create_provider()
    assert error.value.code == "PROVIDER_CONFIG_ERROR"
    assert "fake-secret-never-log" not in "".join(traceback.format_exception(error.value))
