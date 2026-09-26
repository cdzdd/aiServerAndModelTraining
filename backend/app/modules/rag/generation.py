"""Collect a bounded complete provider response before any user-visible output."""

from contextlib import aclosing
from dataclasses import dataclass

from app.modules.providers.base import Provider
from app.modules.providers.errors import ProviderError
from app.modules.providers.schemas import LLMMessage, LLMUsage

from .schemas import RAGError


@dataclass(frozen=True)
class Completion:
    text: str
    usage: LLMUsage | None


async def collect_completion(
    provider: Provider, messages: list[LLMMessage], *, max_tokens: int
) -> Completion:
    parts = []
    size = 0
    stopped = False
    usage = None
    try:
        async with aclosing(
            provider.stream(messages, max_tokens=max_tokens, temperature=0)
        ) as stream:
            async for delta in stream:
                if stopped:
                    raise RAGError("PROVIDER_PROTOCOL_ERROR")
                size += len(delta.text)
                if size > 8192:
                    raise RAGError("RAG_INVALID_OUTPUT")
                parts.append(delta.text)
                if delta.usage is not None:
                    usage = delta.usage
                if delta.finish_reason is not None:
                    if delta.finish_reason != "stop":
                        raise RAGError("PROVIDER_UNSUPPORTED_RESPONSE")
                    stopped = True
    except ProviderError as error:
        raise RAGError(error.code) from None
    if not stopped:
        raise RAGError("PROVIDER_STREAM_INTERRUPTED")
    text = "".join(parts)
    if not text.strip():
        raise RAGError("PROVIDER_EMPTY_RESPONSE")
    return Completion(text, usage)
