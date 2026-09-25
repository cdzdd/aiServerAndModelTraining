from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        CheckConstraint("visibility IN ('public','restricted')", name="knowledge_visibility"),
        CheckConstraint("version >= 1", name="knowledge_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(2000), default="")
    visibility: Mapped[str] = mapped_column(String(10), default="restricted")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class KnowledgeMembership(Base):
    __tablename__ = "knowledge_memberships"

    kb_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_bases.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)


class FAQ(Base):
    __tablename__ = "faqs"
    __table_args__ = (
        CheckConstraint("version >= 1", name="faq_version"),
        CheckConstraint(
            "indexed_version IS NULL OR (indexed_version >= 1 AND indexed_version <= version)",
            name="faq_indexed_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    kb_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    question: Mapped[str] = mapped_column(String(500))
    answer: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    indexed_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
