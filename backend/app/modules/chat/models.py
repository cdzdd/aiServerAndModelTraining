from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


def now():
    return datetime.now(UTC)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("mode IN ('bot','queued','human','closed')", name="conversation_mode"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(50), default="新会话")
    kb_ids: Mapped[list] = mapped_column(JSONB)
    mode: Mapped[str] = mapped_column(String(10), default="bot")
    assigned_agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generation_token: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant','agent','system')", name="message_role"),
        CheckConstraint(
            "status IN ('generating','complete','failed','cancelled')", name="message_status"
        ),
        UniqueConstraint(
            "conversation_id", "author_id", "client_message_id", name="message_client_key"
        ),
        UniqueConstraint("in_reply_to_id", name="message_reply"),
        Index(
            "ix_messages_one_generation",
            "conversation_id",
            unique=True,
            postgresql_where=text("role = 'assistant' AND status = 'generating'"),
        ),
        Index("ix_messages_conversation_order", "conversation_id", "created_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String(10))
    author_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="complete")
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    client_message_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    in_reply_to_id: Mapped[UUID | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    generation_token: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    answer_status: Mapped[str | None] = mapped_column(String(12), nullable=True)
    evidence_level: Mapped[str | None] = mapped_column(String(12), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(12), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    request_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GenerationUsage(Base):
    __tablename__ = "generation_usage"
    __table_args__ = (
        UniqueConstraint("user_message_id", name="generation_usage_request"),
        Index("ix_generation_usage_user_accepted", "user_id", "accepted_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"))
    user_message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id"))
    assistant_message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id"))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(12), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
