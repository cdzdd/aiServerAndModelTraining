import math
from collections.abc import AsyncIterator
from typing import Protocol

from .errors import ProviderError
from .schemas import LLMDelta, LLMMessage


class Provider(Protocol):
    def stream(
        self, messages: list[LLMMessage], *, max_tokens: int, temperature: float
    ) -> AsyncIterator[LLMDelta]: ...


def validate_request(messages, max_tokens, temperature, output_limit):
    if (
        not messages
        or not all(isinstance(message, LLMMessage) for message in messages)
        or type(max_tokens) is not int
        or not 1 <= max_tokens <= output_limit
        or type(temperature) not in (int, float)
        or not math.isfinite(temperature)
        or not 0 <= temperature <= 2
    ):
        raise ProviderError("PROVIDER_BAD_REQUEST")
