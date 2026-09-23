import asyncio
from collections.abc import AsyncIterator

from .base import validate_request
from .schemas import LLMDelta, LLMMessage


class MockProvider:
    def __init__(self, *, max_output_tokens: int = 512):
        self.max_output_tokens = max_output_tokens

    async def stream(
        self, messages: list[LLMMessage], *, max_tokens: int, temperature: float
    ) -> AsyncIterator[LLMDelta]:
        validate_request(messages, max_tokens, temperature, self.max_output_tokens)
        # Character slicing is a deterministic mock budget, not model token accounting.
        text = "Mock：这是用于联调的模拟回答。"
        for char in text[:max_tokens]:
            await asyncio.sleep(0)
            yield LLMDelta(text=char)
        yield LLMDelta(finish_reason="length" if max_tokens < len(text) else "stop")
