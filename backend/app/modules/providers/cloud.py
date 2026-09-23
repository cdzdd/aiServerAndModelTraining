from collections.abc import AsyncIterator

import httpx2 as httpx

from .base import validate_request
from .config import ModelSettings
from .errors import ProviderError
from .schemas import LLMDelta, LLMMessage, LLMUsage


class CloudProvider:
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
            "messages": [m.model_dump() for m in messages],
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        finish_reason = None
        usage = None
        has_text = False
        terminal = None
        try:
            # One client per generation; all context exits close the upstream socket.
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=False, trust_env=False
            ) as client:
                async with client.stream(
                    "POST",
                    settings.model_base_url.rstrip("/") + "/chat/completions",
                    headers={
                        "Authorization": "Bearer " + settings.model_api_key.get_secret_value(),
                        "Accept": "text/event-stream",
                    },
                    json=payload,
                ) as response:
                    status = response.status_code
                    if status in (401, 403):
                        raise ProviderError("PROVIDER_AUTH_FAILED")
                    if status == 429:
                        raise ProviderError("PROVIDER_RATE_LIMITED")
                    if status >= 500:
                        raise ProviderError("PROVIDER_UNAVAILABLE")
                    if status != 200:
                        raise ProviderError("PROVIDER_BAD_REQUEST")
                    async for event in httpx.EventSource(response, max_event_size=65536):
                        if not event.data:
                            continue
                        if event.data == "[DONE]":
                            if finish_reason is None:
                                raise ProviderError("PROVIDER_PROTOCOL_ERROR")
                            if not has_text and finish_reason == "stop":
                                raise ProviderError("PROVIDER_EMPTY_RESPONSE")
                            terminal = LLMDelta(finish_reason=finish_reason, usage=usage)
                            break
                        chunk = event.json()
                        if not isinstance(chunk, dict):
                            raise ProviderError("PROVIDER_PROTOCOL_ERROR")
                        if "error" in chunk:
                            raise ProviderError("PROVIDER_UNAVAILABLE")
                        if chunk.get("usage") is not None:
                            usage = LLMUsage.model_validate(chunk["usage"])
                        choices = chunk["choices"]
                        if not isinstance(choices, list):
                            raise ProviderError("PROVIDER_PROTOCOL_ERROR")
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice["delta"]
                        if not isinstance(delta, dict):
                            raise ProviderError("PROVIDER_PROTOCOL_ERROR")
                        if delta.get("tool_calls") or delta.get("function_call"):
                            raise ProviderError("PROVIDER_UNSUPPORTED_RESPONSE")
                        text = delta.get("content")
                        reason = choice.get("finish_reason")
                        if text is not None and not isinstance(text, str):
                            raise ProviderError("PROVIDER_PROTOCOL_ERROR")
                        if finish_reason is not None and (text or reason):
                            raise ProviderError("PROVIDER_PROTOCOL_ERROR")
                        if reason is not None:
                            if reason not in ("stop", "length", "content_filter"):
                                raise ProviderError("PROVIDER_UNSUPPORTED_RESPONSE")
                            finish_reason = reason
                        if text:
                            has_text = has_text or bool(text.strip())
                            yield LLMDelta(text=text)
                    if terminal is None:
                        raise ProviderError("PROVIDER_STREAM_INTERRUPTED")
        except httpx.TimeoutException:
            raise ProviderError("PROVIDER_TIMEOUT") from None
        except (httpx.SSEError, httpx.DecodingError):
            raise ProviderError("PROVIDER_PROTOCOL_ERROR") from None
        except httpx.TransportError:
            code = "PROVIDER_STREAM_INTERRUPTED" if has_text else "PROVIDER_UNAVAILABLE"
            raise ProviderError(code) from None
        except (ValueError, TypeError, KeyError, IndexError):
            raise ProviderError("PROVIDER_PROTOCOL_ERROR") from None
        # Emit completion only after DONE and after upstream resources have been released.
        yield terminal
