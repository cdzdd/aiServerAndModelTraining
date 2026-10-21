import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.providers.errors import ProviderErrorCode
from app.modules.providers.schemas import LLMMessage

MAX_BODY_BYTES = 65536


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)


class Payload(StrictModel):
    model_id: str = Field(min_length=1, max_length=200)
    messages: list[LLMMessage] = Field(min_length=1)
    max_tokens: int = Field(ge=1, le=512)
    temperature: float = Field(ge=0, allow_inf_nan=False)

    @field_validator("messages")
    @classmethod
    def bounded_prompt(cls, messages):
        if sum(len(message.content.encode("utf-8")) for message in messages) > 12000:
            raise ValueError("Prompt too large")
        return messages


class Usage(StrictModel):
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class SuccessResult(StrictModel):
    model_id: str = Field(min_length=1, max_length=200)
    text: str = Field(max_length=8192)
    finish_reason: Literal["stop", "length"]
    usage: Usage | None


class FailureResult(StrictModel):
    error_code: ProviderErrorCode


class ClaimInput(StrictModel):
    pass


class HeartbeatInput(StrictModel):
    lease_token: str = Field(min_length=1, max_length=128)


class ResultInput(HeartbeatInput):
    result: SuccessResult | FailureResult


def bounded_json(value: dict) -> bytes:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if len(encoded) > MAX_BODY_BYTES:
        raise ValueError("JSON body too large")
    return encoded
