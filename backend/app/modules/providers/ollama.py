"""Ollama /api/chat NDJSON adapted to the shared text provider contract."""

import json
from collections.abc import AsyncIterator

import httpx2 as httpx

from .base import validate_request
from .config import ModelSettings
from .errors import ProviderError
from .schemas import LLMDelta, LLMMessage, LLMUsage


async def _objects(response):
    # Bound each JSON record, including an unfinished record without a newline.
    pending = b""
    async for data in response.aiter_bytes():
        pending += data
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            if len(line) > 65536:
                raise ProviderError("PROVIDER_PROTOCOL_ERROR")
            if line.strip():
                yield json.loads(line.decode("utf-8"))
        if len(pending) > 65536:
            raise ProviderError("PROVIDER_PROTOCOL_ERROR")
    if pending.strip():
        yield json.loads(pending.decode("utf-8"))


class OllamaProvider:
    def __init__(self, settings: ModelSettings):
        self.settings = settings

    async def stream(
        self, messages: list[LLMMessage], *, max_tokens: int, temperature: float
    ) -> AsyncIterator[LLMDelta]:
        settings = self.settings
        validate_request(messages, max_tokens, temperature, settings.model_max_output_tokens)
        timeout = httpx.Timeout(
            settings.model_read_timeout_seconds, connect=settings.model_connect_timeout_seconds
        )
        payload = {
            "model": settings.model_id,
            "messages": [message.model_dump() for message in messages],
            "stream": True,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
                "num_ctx": settings.ollama_num_ctx,
            },
        }
        if settings.model_disable_thinking:
            payload["think"] = False
        has_text = False
        terminal = None
        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=False, trust_env=False
            ) as client:
                async with client.stream(
                    "POST",
                    settings.model_base_url.rstrip("/") + "/api/chat",
                    headers={"Accept": "application/x-ndjson"},
                    json=payload,
                ) as response:
                    status = response.status_code
                    if status in (401, 403):
                        raise ProviderError("PROVIDER_AUTH_FAILED")
                    if status == 429:
                        raise ProviderError("PROVIDER_RATE_LIMITED")
                    if status == 404 or status >= 500:
                        raise ProviderError("PROVIDER_UNAVAILABLE")
                    if status != 200:
                        raise ProviderError("PROVIDER_BAD_REQUEST")
                    if response.headers.get("content-type", "").split(";")[0].strip() != (
                        "application/x-ndjson"
                    ):
                        raise ProviderError("PROVIDER_PROTOCOL_ERROR")
                    async for chunk in _objects(response):
                        if not isinstance(chunk, dict):
                            raise ProviderError("PROVIDER_PROTOCOL_ERROR")
                        if "error" in chunk:
                            raise ProviderError("PROVIDER_UNAVAILABLE")
                        done = chunk["done"]
                        reason = chunk.get("done_reason")
                        if type(done) is not bool or (not done and reason is not None):
                            raise ProviderError("PROVIDER_PROTOCOL_ERROR")
                        message = chunk.get("message", {} if done else None)
                        if not isinstance(message, dict):
                            raise ProviderError("PROVIDER_PROTOCOL_ERROR")
                        if message.get("tool_calls") or message.get("images"):
                            raise ProviderError("PROVIDER_UNSUPPORTED_RESPONSE")
                        text = message.get("content", "")
                        if not isinstance(text, str):
                            raise ProviderError("PROVIDER_PROTOCOL_ERROR")
                        text.encode("utf-8")
                        if done:
                            if reason is None:
                                raise ProviderError("PROVIDER_PROTOCOL_ERROR")
                            if reason not in ("stop", "length"):
                                raise ProviderError("PROVIDER_UNSUPPORTED_RESPONSE")
                            usage = None
                            prompt = chunk.get("prompt_eval_count")
                            completion = chunk.get("eval_count")
                            if prompt is not None or completion is not None:
                                usage = LLMUsage(prompt_tokens=prompt, completion_tokens=completion)
                            if not (has_text or text.strip()) and reason == "stop":
                                raise ProviderError("PROVIDER_EMPTY_RESPONSE")
                            terminal = LLMDelta(finish_reason=reason, usage=usage)
                        if text:
                            has_text = has_text or bool(text.strip())
                            yield LLMDelta(text=text)
                        if done:
                            break
                    if terminal is None:
                        raise ProviderError("PROVIDER_STREAM_INTERRUPTED")
        except httpx.TimeoutException:
            raise ProviderError("PROVIDER_TIMEOUT") from None
        except httpx.DecodingError:
            raise ProviderError("PROVIDER_PROTOCOL_ERROR") from None
        except httpx.TransportError:
            code = "PROVIDER_STREAM_INTERRUPTED" if has_text else "PROVIDER_UNAVAILABLE"
            raise ProviderError(code) from None
        except (ValueError, TypeError, KeyError, RecursionError):
            raise ProviderError("PROVIDER_PROTOCOL_ERROR") from None
        # Match CloudProvider: release the socket before exposing the terminal delta.
        yield terminal
