from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


def now():
    return datetime.now(UTC)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded','processing','parsed','ready','failed','disabled','deleted')",
            name="document_status",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    kb_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    active_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    candidate_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DocumentRevision(Base):
    __tablename__ = "document_revisions"
    __table_args__ = (UniqueConstraint("document_id", "content_sha256", name="revision_content"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(36))
    file_type: Mapped[str] = mapped_column(String(5))
    parser_version: Mapped[str] = mapped_column(String(100), default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        CheckConstraint(
            "(document_id IS NOT NULL) <> (faq_id IS NOT NULL)", name="chunk_one_source"
        ),
        UniqueConstraint("revision_id", "chunk_index", name="chunk_revision_index"),
        UniqueConstraint("faq_id", "faq_version", "chunk_index", name="chunk_faq_index"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    kb_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    faq_id: Mapped[UUID | None] = mapped_column(ForeignKey("faqs.id"), nullable=True)
    revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_revisions.id"), nullable=True
    )
    faq_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(255))
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paragraph_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Vector storage and indexed model metadata are added by 007.
    embedding_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(100), nullable=True)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint("kind IN ('parse','index')", name="ingestion_kind"),
        CheckConstraint(
            "state IN ('queued','running','succeeded','failed')", name="ingestion_state"
        ),
        CheckConstraint("(document_id IS NOT NULL) <> (faq_id IS NOT NULL)", name="job_one_source"),
        CheckConstraint(
            "kind <> 'parse' OR (document_id IS NOT NULL AND revision_id IS NOT NULL)",
            name="parse_revision",
        ),
        UniqueConstraint("kind", "revision_id", name="job_revision_kind"),
        UniqueConstraint("kind", "faq_id", "faq_version", name="job_faq_kind_version"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(10))
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id"), nullable=True, index=True
    )
    faq_id: Mapped[UUID | None] = mapped_column(ForeignKey("faqs.id"), nullable=True)
    revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_revisions.id"), nullable=True
    )
    faq_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(String(10), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
