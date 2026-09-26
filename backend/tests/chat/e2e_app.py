"""Test-only browser app and synthetic indexing fixture; never a production switch."""

import asyncio
import json
import sys
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import create_db_engine
from app.modules.ingestion.models import Chunk, Document, DocumentRevision, IngestionJob
from app.modules.knowledge.models import KnowledgeBase
from app.modules.rag.schemas import AnswerEvent, Citation
from app.modules.retrieval.embedding import MODEL_ID, MODEL_REVISION
from app.modules.retrieval.repository import active_candidates


def local_settings():
    settings = Settings()
    url = make_url(settings.database_url.get_secret_value())
    if settings.app_env == "production" or url.host not in ("127.0.0.1", "localhost"):
        raise RuntimeError("Browser fixtures require a local development database")
    return settings


class BrowserRAG:
    def __init__(self, factory):
        self.factory = factory

    def evidence(self, actor, kb_ids):
        with self.factory() as db:
            chunk = db.scalar(active_candidates(actor, kb_ids).order_by(Chunk.id).limit(1))
            if chunk is None:
                return None
            return Citation(
                index=1,
                chunk_id=chunk.id,
                kb_id=chunk.kb_id,
                source_type="document" if chunk.document_id else "faq",
                source_id=chunk.document_id or chunk.faq_id,
                title=chunk.title,
                quote=chunk.text,
                revision_id=chunk.revision_id,
                faq_version=chunk.faq_version,
                page_number=chunk.page_number,
                paragraph_number=chunk.paragraph_number,
                line_number=chunk.line_number,
            )

    async def stream_answer(self, actor, kb_ids, question, history):
        citation = await asyncio.to_thread(self.evidence, actor, kb_ids)
        content = (
            ("结合前文，" if history else "") + "资料原文：" + citation.quote + " [1]"
            if citation
            else "当前可访问资料中没有依据。"
        )
        yield AnswerEvent(type="delta", payload={"text": content})
        yield AnswerEvent(
            type="citations",
            payload={
                "items": [citation.model_dump(mode="json")] if citation else [],
            },
        )
        if "慢速" in question:
            await asyncio.sleep(60)
        yield AnswerEvent(
            type="done",
            payload={
                "answer_status": "answered" if citation else "no_answer",
                "evidence_level": "sufficient" if citation else "none",
                "intent": "knowledge",
                "usage": None,
            },
        )


def create_app():
    from app.main import create_app as application

    app = application(local_settings())
    app.state.chat_rag = BrowserRAG(app.state.session_factory)
    return app


def seed_uploaded_document():
    """Make one explicitly named synthetic upload queryable without an embedding model."""
    settings = local_settings()
    payload = json.load(sys.stdin)
    document_id = UUID(payload["document_id"])
    engine = create_db_engine(settings)
    try:
        with Session(engine) as db:
            document = db.get(Document, document_id)
            if document is None or document.status != "uploaded":
                raise ValueError("Expected a fresh synthetic upload")
            kb = db.get(KnowledgeBase, document.kb_id)
            if not kb.name.startswith("chat-e2e-"):
                raise ValueError("Expected chat-e2e- knowledge name")
            revision = db.get(DocumentRevision, document.candidate_revision_id)
            if revision.file_type != "txt":
                raise ValueError("Expected UTF-8 TXT synthetic fixture")
            text = (
                (settings.upload_dir / str(UUID(revision.storage_key)))
                .read_text(encoding="utf-8-sig")
                .strip()
            )
            if not 1 <= len(text) <= 800:
                raise ValueError("Synthetic text must be 1 to 800 characters")
            chunk = Chunk(
                kb_id=kb.id,
                document_id=document.id,
                revision_id=revision.id,
                chunk_index=0,
                text=text,
                title=document.filename,
                line_number=1,
                embedding=[1.0] + [0.0] * 511,
                embedding_model=MODEL_ID,
                embedding_version=MODEL_REVISION,
            )
            db.add(chunk)
            document.active_revision_id = revision.id
            document.status = "ready"
            for job in db.scalars(
                select(IngestionJob).where(
                    IngestionJob.document_id == document.id,
                )
            ):
                job.state = "succeeded"
            db.flush()
            result = {"chunk_id": str(chunk.id), "document_id": str(document.id)}
            db.commit()
            print(json.dumps(result))
    finally:
        engine.dispose()


if __name__ == "__main__":
    seed_uploaded_document()
