from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LLMMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    role: Literal["system", "user", "assistant"]
    content: str


class LLMUsage(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, hide_input_in_errors=True)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class LLMDelta(BaseModel):
    model_config = ConfigDict(frozen=True)
    text: str = ""
    finish_reason: str | None = None
    usage: LLMUsage | None = None
