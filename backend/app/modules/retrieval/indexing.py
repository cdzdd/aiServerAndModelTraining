"""Recoverable index-only worker; expensive encoding never holds database locks."""

import sys
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import create_db_engine
from app.modules.ingestion.chunking import load_tokenizer, split_sections
from app.modules.ingestion.models import Chunk, Document, IngestionJob
from app.modules.ingestion.parsers import ParseError, Section
from app.modules.ingestion.worker import claim_job
from app.modules.knowledge.models import FAQ, KnowledgeBase
from app.modules.retrieval.embedding import MODEL_ID, MODEL_REVISION, BGEEmbedder, EmbeddingError
from app.modules.retrieval.jobs import enqueue_faq_index


def locked_state(db, claimed):
    model = Document if claimed.document_id else FAQ
    source_id = claimed.document_id or claimed.faq_id
    kb_id = db.scalar(select(model.kb_id).where(model.id == source_id))
    kb = db.scalar(
        select(KnowledgeBase)
        .where(KnowledgeBase.id == kb_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    source = db.scalar(
        select(model)
        .where(model.id == source_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    job = db.scalar(
        select(IngestionJob)
        .where(IngestionJob.id == claimed.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return kb, source, job


def owns_lease(job, claimed):
    return (
        job.state == "running"
        and job.lease_token == claimed.lease_token
        and job.lease_until is not None
        and job.lease_until > datetime.now(UTC)
    )


def valid_source(kb, source, claimed):
    if not kb.is_active:
        return False
    if claimed.document_id:
        return (
            source.status not in {"disabled", "deleted"}
            and source.candidate_revision_id == claimed.revision_id
        )
    return source.is_active and source.version == claimed.faq_version


def renew_lease(factory, claimed):
    with factory() as db:
        now = datetime.now(UTC)
        result = db.execute(
            update(IngestionJob)
            .where(
                IngestionJob.id == claimed.id,
                IngestionJob.state == "running",
                IngestionJob.lease_token == claimed.lease_token,
                IngestionJob.lease_until > now,
            )
            .values(lease_until=now + timedelta(seconds=90))
        )
        db.commit()
        return result.rowcount == 1


def document_chunks(db, claimed):
    return list(
        db.scalars(
            select(Chunk)
            .where(
                Chunk.document_id == claimed.document_id,
                Chunk.revision_id == claimed.revision_id,
            )
            .order_by(Chunk.chunk_index)
        )
    )


def process_job(factory, settings, claimed, *, embedder, tokenizer=None):
    if claimed.kind != "index":
        return
    code = None
    texts = []
    snapshot = []
    with factory() as db:
        kb, source, job = locked_state(db, claimed)
        if not owns_lease(job, claimed):
            return
        if not valid_source(kb, source, claimed):
            code = "SUPERSEDED"
        elif claimed.document_id:
            chunks = document_chunks(db, claimed)
            snapshot = [(chunk.id, chunk.text) for chunk in chunks]
            texts = [chunk.text for chunk in chunks]
        else:
            faq_text = source.question + "\n" + source.answer
        # Release locks before tokenization or model inference.
    vectors = []
    try:
        if code is None:
            if claimed.faq_id:
                sections = split_sections(
                    [Section(text=faq_text)],
                    tokenizer
                    if tokenizer is not None
                    else load_tokenizer(settings.embedding_tokenizer_path),
                )
                texts = [section.text for section in sections]
            if not texts:
                raise ParseError("NO_TEXT")
            for start in range(0, len(texts), 16):
                if not renew_lease(factory, claimed):
                    return
                vectors.extend(embedder.encode_passages(texts[start : start + 16]))
            if not renew_lease(factory, claimed):
                return
    except (EmbeddingError, ParseError) as exc:
        code = exc.code
    with factory() as db:
        kb, source, job = locked_state(db, claimed)
        if not owns_lease(job, claimed):
            return
        if not valid_source(kb, source, claimed):
            code = "SUPERSEDED"
        if claimed.document_id:
            chunks = document_chunks(db, claimed)
            if code is None and snapshot != [(chunk.id, chunk.text) for chunk in chunks]:
                code = "SUPERSEDED"
        if code:
            job.state = "failed"
            job.error_code = code
            if claimed.document_id:
                if (
                    source.status not in {"disabled", "deleted"}
                    and source.candidate_revision_id == claimed.revision_id
                ):
                    source.status = "failed"
            elif kb.is_active and source.is_active and source.version != claimed.faq_version:
                enqueue_faq_index(db, source)
        else:
            if claimed.faq_id:
                existing = {
                    chunk.chunk_index: chunk
                    for chunk in db.scalars(
                        select(Chunk).where(
                            Chunk.faq_id == source.id, Chunk.faq_version == source.version
                        )
                    )
                }
                chunks = []
                for index, text in enumerate(texts):
                    chunk = existing.get(index)
                    if chunk is None:
                        chunk = Chunk(
                            kb_id=kb.id,
                            faq_id=source.id,
                            faq_version=source.version,
                            chunk_index=index,
                            text=text,
                            title=source.question[:255],
                        )
                        db.add(chunk)
                    chunks.append(chunk)
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.embedding = vector
                chunk.embedding_model = MODEL_ID
                chunk.embedding_version = MODEL_REVISION
            if claimed.document_id:
                source.active_revision_id = claimed.revision_id
                source.status = "ready"
            else:
                source.indexed_version = claimed.faq_version
            job.state = "succeeded"
        job.finished_at = datetime.now(UTC)
        job.lease_until = None
        job.lease_token = None
        db.commit()


def main():
    settings = Settings()
    embedder = BGEEmbedder(settings.embedding_model_path)
    embedder.load()
    engine = create_db_engine(settings)
    factory = sessionmaker(engine, expire_on_commit=False)
    once = "--once" in sys.argv
    try:
        while True:
            job = claim_job(factory, kind="index")
            if job:
                process_job(factory, settings, job, embedder=embedder)
            elif not once:
                time.sleep(1)
            if once:
                break
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
