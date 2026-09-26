"""Authorization and active-source filtering happen inside the vector SQL query."""

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.modules.auth.schemas import Actor
from app.modules.ingestion.models import Chunk, Document, DocumentRevision
from app.modules.knowledge.models import FAQ, KnowledgeBase
from app.modules.knowledge.permissions import visible_condition
from app.modules.retrieval.embedding import MODEL_ID, MODEL_REVISION
from app.modules.retrieval.schemas import RetrievalError, SearchHit


def has_visible_scope(db: Session, actor: Actor, kb_ids: list[UUID]) -> bool:
    return (
        db.scalar(
            select(KnowledgeBase.id)
            .where(KnowledgeBase.id.in_(kb_ids), visible_condition(actor))
            .limit(1)
        )
        is not None
    )


def active_candidates(actor: Actor, kb_ids: list[UUID]):
    document_active = and_(
        Chunk.document_id == Document.id,
        Chunk.kb_id == Document.kb_id,
        Document.status.not_in(["disabled", "deleted"]),
        Chunk.revision_id == Document.active_revision_id,
        DocumentRevision.document_id == Document.id,
    )
    faq_active = and_(
        Chunk.faq_id == FAQ.id,
        Chunk.kb_id == FAQ.kb_id,
        FAQ.is_active.is_(True),
        FAQ.indexed_version == FAQ.version,
        Chunk.faq_version == FAQ.version,
    )
    return (
        select(Chunk)
        .join(KnowledgeBase, KnowledgeBase.id == Chunk.kb_id)
        .outerjoin(Document, Document.id == Chunk.document_id)
        .outerjoin(DocumentRevision, DocumentRevision.id == Chunk.revision_id)
        .outerjoin(FAQ, FAQ.id == Chunk.faq_id)
        .where(
            Chunk.kb_id.in_(kb_ids),
            visible_condition(actor),
            or_(document_active, faq_active),
            Chunk.embedding.is_not(None),
        )
    )


def search_candidates(
    db: Session,
    actor: Actor,
    kb_ids: list[UUID],
    vector: list[float],
    *,
    top_k: int,
    threshold: float,
) -> list[SearchHit]:
    candidates = active_candidates(actor, kb_ids)
    mismatched = or_(
        Chunk.embedding_model.is_distinct_from(MODEL_ID),
        Chunk.embedding_version.is_distinct_from(MODEL_REVISION),
    )
    if db.scalar(candidates.with_only_columns(Chunk.id).where(mismatched).limit(1)):
        raise RetrievalError("MODEL_INDEX_MISMATCH")

    distance = Chunk.embedding.cosine_distance(vector)
    score = (1 - distance).label("score")
    ranked = (
        candidates.add_columns(score)
        .where(
            Chunk.embedding_model == MODEL_ID,
            Chunk.embedding_version == MODEL_REVISION,
            score >= threshold,
        )
        .order_by(distance, Chunk.id)
        .limit(top_k)
    )
    return [
        SearchHit(
            chunk_id=chunk.id,
            kb_id=chunk.kb_id,
            text=chunk.text,
            source_type="document" if chunk.document_id else "faq",
            source_id=chunk.document_id or chunk.faq_id,
            title=chunk.title,
            score=float(similarity),
            page_number=chunk.page_number,
            revision_id=chunk.revision_id,
            faq_version=chunk.faq_version,
            paragraph_number=chunk.paragraph_number,
            line_number=chunk.line_number,
        )
        for chunk, similarity in db.execute(ranked)
    ]
