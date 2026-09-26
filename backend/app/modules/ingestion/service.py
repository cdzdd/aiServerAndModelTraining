from uuid import UUID

from fastapi import Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.security import AuthError
from app.modules.auth.schemas import Actor
from app.modules.ingestion.models import Chunk, Document, DocumentRevision, IngestionJob
from app.modules.ingestion.parsers import ERROR_MESSAGES as PARSE_ERROR_MESSAGES
from app.modules.ingestion.schemas import DocumentSummary, JobSummary, RevisionSummary
from app.modules.ingestion.storage import store_upload
from app.modules.knowledge.permissions import require_read
from app.modules.knowledge.service import locked_kb, paginate

ERROR_MESSAGES = {
    **PARSE_ERROR_MESSAGES,
    "MODEL_UNAVAILABLE": "向量模型尚不可用，请联系管理员后重试",
    "MODEL_INTEGRITY": "向量模型文件不完整或版本不符，请联系管理员",
    "INVALID_INPUT": "索引内容无有效文本，请检查后重新上传",
    "TOKEN_LIMIT": "索引片段超过模型长度上限，请检查分段设置",
    "ENCODE_FAILED": "向量生成失败，请稍后重新索引",
    "INVALID_OUTPUT": "向量模型输出无效，请联系管理员后重试",
}


def get_document(db: Session, actor: Actor, document_id: UUID, *, lock=False):
    kb_id = db.scalar(select(Document.kb_id).where(Document.id == document_id))
    if kb_id is None:
        raise AuthError(404, "NOT_FOUND", "资源不存在或不可见")
    if lock:
        locked_kb(db, kb_id, active=True)
    require_read(db, actor, kb_id)
    statement = select(Document).where(Document.id == document_id)
    document = db.scalar(
        statement.with_for_update().execution_options(populate_existing=True) if lock else statement
    )
    if document.status == "deleted" or (document.status == "disabled" and actor.role != "admin"):
        raise AuthError(404, "NOT_FOUND", "资源不存在或不可见")
    return document


def latest_job(db, document):
    return db.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.document_id == document.id,
            IngestionJob.revision_id == document.candidate_revision_id,
        )
        .order_by(IngestionJob.created_at.desc(), IngestionJob.id)
        .limit(1)
    )


def summary(db, document):
    result = DocumentSummary.model_validate(document)
    for key in ("active_revision", "candidate_revision"):
        revision_id = getattr(document, key + "_id")
        if revision_id:
            setattr(
                result, key, RevisionSummary.model_validate(db.get(DocumentRevision, revision_id))
            )
    job = latest_job(db, document)
    if job:
        result.latest_job = JobSummary.model_validate(job)
        result.latest_job.error_message = ERROR_MESSAGES.get(job.error_code)
    return result


def list_documents(db, actor, kb_id, page, page_size):
    require_read(db, actor, kb_id)
    statement = select(Document).where(Document.kb_id == kb_id, Document.status != "deleted")
    if actor.role != "admin":
        statement = statement.where(Document.status != "disabled")
    result = paginate(
        db, statement.order_by(Document.created_at.desc(), Document.id), page, page_size
    )
    result["items"] = [summary(db, document) for document in result["items"]]
    return result


def audit(db, request, actor, document, action):
    record_audit(
        db,
        actor_id=actor.user_id,
        action="document." + action,
        target_type="document",
        target_id=str(document.id),
        outcome="success",
        request_id=request.state.request_id,
        metadata={"kb_id": str(document.kb_id)},
    )


def enqueue(db, document, kind):
    job = db.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.kind == kind, IngestionJob.revision_id == document.candidate_revision_id
        )
        .with_for_update()
    )
    if job is None:
        job = IngestionJob(
            kind=kind, document_id=document.id, revision_id=document.candidate_revision_id
        )
        db.add(job)
        db.flush()
    elif job.state not in {"queued", "running"}:
        job.state = "queued"
        job.error_code = None
        job.finished_at = None
        job.lease_until = None
        job.lease_token = None
    return job


def upload(
    db: Session,
    request: Request,
    actor: Actor,
    kb_id: UUID,
    file: UploadFile,
    document_id: UUID | None = None,
):
    # Serialize deduplication and revision selection with other knowledge writes.
    locked_kb(db, kb_id, active=True)
    document = get_document(db, actor, document_id, lock=True) if document_id else None
    if document and document.status == "disabled":
        raise AuthError(409, "CONFLICT", "请先启用文档")
    key, digest, suffix = store_upload(request.app.state.settings.upload_dir, file)
    keep = False
    try:
        if document is None:
            document = db.scalar(
                select(Document)
                .join(DocumentRevision, Document.candidate_revision_id == DocumentRevision.id)
                .where(
                    Document.kb_id == kb_id,
                    Document.filename == file.filename,
                    Document.status.not_in(["deleted", "disabled"]),
                    DocumentRevision.content_sha256 == digest,
                )
                .with_for_update(of=Document)
            )
        if document is not None:
            revision = db.scalar(
                select(DocumentRevision).where(
                    DocumentRevision.document_id == document.id,
                    DocumentRevision.content_sha256 == digest,
                )
            )
            if revision:
                if document.candidate_revision_id != revision.id:
                    raise AuthError(409, "CONFLICT", "该文件已存在于历史版本，请上传新内容")
                job = latest_job(db, document)
                return {"document_id": document.id, "job_id": job.id, "status": "uploaded"}
        else:
            document = Document(kb_id=kb_id, filename=file.filename)
            db.add(document)
            db.flush()
        revision = DocumentRevision(
            document_id=document.id,
            filename=file.filename,
            content_sha256=digest,
            storage_key=key,
            file_type=suffix,
        )
        db.add(revision)
        db.flush()
        document.candidate_revision_id = revision.id
        document.filename = file.filename
        document.status = "uploaded"
        job = enqueue(db, document, "parse")
        audit(db, request, actor, document, "replace" if document_id else "upload")
        db.commit()
        keep = True
        return {"document_id": document.id, "job_id": job.id, "status": "uploaded"}
    finally:
        if not keep:
            (request.app.state.settings.upload_dir / key).unlink(missing_ok=True)


def patch_document(db, request, actor, document_id, enabled):
    document = get_document(db, actor, document_id, lock=True)
    if not enabled:
        document.status = "disabled"
    elif document.status == "disabled":
        job = latest_job(db, document)
        if job and job.state == "failed":
            document.status = "failed"
        elif job and job.kind == "index":
            document.status = (
                "ready"
                if document.active_revision_id == document.candidate_revision_id
                else "parsed"
            )
        else:
            document.status = "uploaded"
    audit(db, request, actor, document, "enable" if enabled else "disable")
    db.commit()
    return summary(db, document)


def delete_document(db, request, actor, document_id):
    document = get_document(db, actor, document_id, lock=True)
    document.status = "deleted"
    audit(db, request, actor, document, "delete")
    db.commit()


def retry(db, request, actor, document_id):
    document = get_document(db, actor, document_id, lock=True)
    if document.status == "disabled":
        raise AuthError(409, "CONFLICT", "请先启用文档")
    parsed = db.scalar(
        select(Chunk.id).where(Chunk.revision_id == document.candidate_revision_id).limit(1)
    )
    kind = "index" if parsed else "parse"
    job = enqueue(db, document, kind)
    document.status = "parsed" if parsed else "uploaded"
    audit(db, request, actor, document, "retry")
    db.commit()
    return {"job_id": job.id}
