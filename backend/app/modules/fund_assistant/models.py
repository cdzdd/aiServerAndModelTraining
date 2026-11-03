from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class FundSubject(Base):
    __tablename__ = "fund_assistant_subjects"

    subject: Mapped[str] = mapped_column(String(19), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), unique=True)


class FundConversation(Base):
    __tablename__ = "fund_assistant_conversations"

    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    subject: Mapped[str] = mapped_column(ForeignKey("fund_assistant_subjects.subject"), index=True)
    kb_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_bases.id"))
