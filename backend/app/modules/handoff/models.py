from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class Handoff(Base):
    __tablename__ = "handoffs"
    __table_args__ = (
        UniqueConstraint("conversation_id", name="handoff_conversation"),
        CheckConstraint(
            "(claimed_at IS NULL) = (claimed_by_id IS NULL)", name="handoff_claim_pair"
        ),
        CheckConstraint("(closed_at IS NULL) = (closed_by_id IS NULL)", name="handoff_close_pair"),
        Index("ix_handoffs_queue_order", "requested_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
