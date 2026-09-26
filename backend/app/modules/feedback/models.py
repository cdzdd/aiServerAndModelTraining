from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


def now():
    return datetime.now(UTC)


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "message_id", name="feedback_user_message"),
        CheckConstraint("rating IN ('up','down')", name="feedback_rating"),
        CheckConstraint("status IN ('open','resolved')", name="feedback_status"),
        Index("ix_feedback_status_created_id", "status", "created_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id"), index=True)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    rating: Mapped[str] = mapped_column(String(4))
    comment: Mapped[str] = mapped_column(Text, default="")
    source_versions: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(10), default="open")
    resolution: Mapped[str] = mapped_column(Text, default="")
    resolved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
