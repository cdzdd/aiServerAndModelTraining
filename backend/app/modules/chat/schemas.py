from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from app.modules.auth.schemas import Actor, clean_display_name
from app.modules.providers.schemas import LLMMessage
from app.modules.rag.schemas import Citation

Mode = Literal["bot", "queued", "human", "closed"]
MessageStatus = Literal["generating", "complete", "failed", "cancelled"]
Content = Annotated[str, BeforeValidator(clean_display_name), Field(min_length=1, max_length=2000)]


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kb_ids: list[UUID] = Field(min_length=1, max_length=50)

    @field_validator("kb_ids")
    @classmethod
    def unique_scope(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("知识库不能重复")
        return values


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: Content
    client_message_id: UUID


class ConversationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    title: str
    kb_ids: list[UUID]
    mode: Mode
    assigned_agent_id: UUID | None
    created_at: datetime
    updated_at: datetime


class MessageView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    role: Literal["user", "assistant", "agent", "system"]
    author_id: UUID | None
    content: str
    status: MessageStatus
    citations: list[Citation]
    client_message_id: UUID | None
    in_reply_to_id: UUID | None
    answer_status: Literal["answered", "clarify", "no_answer"] | None
    evidence_level: Literal["sufficient", "limited", "none"] | None
    intent: Literal["knowledge", "complaint", "handoff", "other"] | None
    latency_ms: int | None
    error_code: str | None
    created_at: datetime
    evidence_hidden: bool = False


class ConversationPage(BaseModel):
    items: list[ConversationView]
    total: int
    page: int
    page_size: int


class MessagePage(BaseModel):
    items: list[MessageView]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class GenerationReservation:
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    token: UUID
    actor: Actor
    kb_ids: list[UUID]
    question: str
    history: list[LLMMessage]
    accepted_at: datetime
    request_id: str
