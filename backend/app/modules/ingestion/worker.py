import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import create_db_engine
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.ingestion.chunking import split_sections
from app.modules.ingestion.models import Chunk, Document, DocumentRevision, IngestionJob
from app.modules.ingestion.parsers import ParseError, Section, parse_file
from app.modules.knowledge.models import KnowledgeBase


def claim_job(factory, *, kind="parse", lease_seconds=90):
    """Short atomic claim; lease_token fences workers surviving a lease recovery."""
    with factory() as db:
        now = datetime.now(UTC)
        job = db.scalar(
            select(IngestionJob)
            .where(
                IngestionJob.kind == kind,
                or_(
                    IngestionJob.state == "queued",
                    (IngestionJob.state == "running") & (IngestionJob.lease_until < now),
                ),
            )
            .order_by(IngestionJob.created_at, IngestionJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        job.state = "running"
        job.attempts += 1
        job.lease_token = uuid4()
        job.lease_until = now + timedelta(seconds=lease_seconds)
        job.error_code = None
        db.commit()
        db.refresh(job)
        db.expunge(job)
        return job


def bounded_parse(settings, revision):
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.modules.ingestion.parse_runner",
                str(settings.upload_dir / revision.storage_key),
                revision.file_type,
                settings.embedding_tokenizer_path,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=settings.ingestion_parse_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ParseError("PARSE_TIMEOUT") from exc
    if result.returncode:
        raise ParseError("PARSE_FAILED")
    try:
        data = json.loads(result.stdout)
        if "error" in data:
            raise ParseError(data["error"])
        return [Section(**item) for item in data["chunks"]]
    except (ValueError, KeyError, TypeError) as exc:
        raise ParseError("PARSE_FAILED") from exc


def process_job(factory, settings, claimed, *, tokenizer=None):
    if claimed.kind != "parse":
        return
    with factory() as db:
        kb_id = db.scalar(select(Document.kb_id).where(Document.id == claimed.document_id))
        kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id).with_for_update())
        document = db.scalar(
            select(Document).where(Document.id == claimed.document_id).with_for_update()
        )
        job = db.scalar(select(IngestionJob).where(IngestionJob.id == claimed.id).with_for_update())
        if job.state != "running" or job.lease_token != claimed.lease_token:
            return
        revision = db.get(DocumentRevision, claimed.revision_id)
        if (
            kb.is_active
            and document.status not in {"disabled", "deleted"}
            and document.candidate_revision_id == revision.id
        ):
            document.status = "processing"
        db.commit()
        db.expunge(revision)
    code = None
    chunks = []
    try:
        chunks = (
            split_sections(
                parse_file(settings.upload_dir / revision.storage_key, revision.file_type),
                tokenizer,
            )
            if tokenizer is not None
            else bounded_parse(settings, revision)
        )
    except ParseError as exc:
        code = exc.code
    # Same lock order as administrative changes: KB, document, job.
    with factory() as db:
        kb_id = db.scalar(select(Document.kb_id).where(Document.id == claimed.document_id))
        kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id).with_for_update())
        document = db.scalar(
            select(Document).where(Document.id == claimed.document_id).with_for_update()
        )
        job = db.scalar(select(IngestionJob).where(IngestionJob.id == claimed.id).with_for_update())
        if job.state != "running" or job.lease_token != claimed.lease_token:
            return
        valid = (
            kb.is_active
            and document.status not in {"disabled", "deleted"}
            and document.candidate_revision_id == claimed.revision_id
        )
        if not valid:
            code = "SUPERSEDED"
        if code:
            job.state = "failed"
            job.error_code = code
            if (
                document.status not in {"disabled", "deleted"}
                and document.candidate_revision_id == claimed.revision_id
            ):
                document.status = "failed"
        else:
            db.execute(delete(Chunk).where(Chunk.revision_id == revision.id))
            db.add_all(
                Chunk(
                    kb_id=kb.id,
                    document_id=document.id,
                    revision_id=revision.id,
                    chunk_index=index,
                    text=chunk.text,
                    title=revision.filename,
                    page_number=chunk.page_number,
                    paragraph_number=chunk.paragraph_number,
                    line_number=chunk.line_number,
                )
                for index, chunk in enumerate(chunks)
            )
            index_job = db.scalar(
                select(IngestionJob).where(
                    IngestionJob.kind == "index", IngestionJob.revision_id == revision.id
                )
            )
            if index_job is None:
                db.add(IngestionJob(kind="index", document_id=document.id, revision_id=revision.id))
            document.status = "parsed"
            job.state = "succeeded"
        job.finished_at = datetime.now(UTC)
        job.lease_until = None
        job.lease_token = None
        db.commit()


def main():
    settings = Settings()
    engine = create_db_engine(settings)
    factory = sessionmaker(engine, expire_on_commit=False)
    once = "--once" in sys.argv
    try:
        while True:
            job = claim_job(factory, lease_seconds=settings.ingestion_parse_timeout + 30)
            if job:
                process_job(factory, settings, job)
            elif not once:
                time.sleep(1)
            if once:
                break
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
