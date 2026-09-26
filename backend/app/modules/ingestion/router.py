from uuid import UUID

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import FileResponse

from app.core.security import AuthError
from app.modules.ingestion import service
from app.modules.ingestion.models import DocumentRevision
from app.modules.ingestion.schemas import (
    DocumentPage,
    DocumentPatch,
    DocumentSummary,
    RetryResult,
    UploadResult,
)
from app.modules.knowledge.router import Admin, CurrentActor, Database, Page, PageSize

router = APIRouter(prefix="/api/v1", tags=["documents"])


@router.get("/knowledge-bases/{kb_id}/documents", response_model=DocumentPage)
def list_documents(
    kb_id: UUID, db: Database, actor: CurrentActor, page: Page = 1, page_size: PageSize = 20
):
    return service.list_documents(db, actor, kb_id, page, page_size)


@router.post("/knowledge-bases/{kb_id}/documents", status_code=202, response_model=UploadResult)
def upload(kb_id: UUID, file: UploadFile, request: Request, db: Database, actor: Admin):
    return service.upload(db, request, actor, kb_id, file)


@router.post("/documents/{document_id}/revisions", status_code=202, response_model=UploadResult)
def revision(document_id: UUID, file: UploadFile, request: Request, db: Database, actor: Admin):
    document = service.get_document(db, actor, document_id)
    return service.upload(db, request, actor, document.kb_id, file, document_id)


@router.get("/documents/{document_id}", response_model=DocumentSummary)
def detail(document_id: UUID, db: Database, actor: CurrentActor):
    return service.summary(db, service.get_document(db, actor, document_id))


@router.patch("/documents/{document_id}", response_model=DocumentSummary)
def patch(document_id: UUID, data: DocumentPatch, request: Request, db: Database, actor: Admin):
    return service.patch_document(db, request, actor, document_id, data.is_active)


@router.delete("/documents/{document_id}", status_code=204)
def delete(document_id: UUID, request: Request, db: Database, actor: Admin):
    service.delete_document(db, request, actor, document_id)


@router.post("/documents/{document_id}/reindex", status_code=202, response_model=RetryResult)
def retry(document_id: UUID, request: Request, db: Database, actor: Admin):
    return service.retry(db, request, actor, document_id)


@router.get("/documents/{document_id}/download")
def download(document_id: UUID, request: Request, db: Database, actor: CurrentActor):
    document = service.get_document(db, actor, document_id)
    if document.status == "disabled":
        raise AuthError(404, "NOT_FOUND", "资源不存在或不可见")
    revision = db.get(
        DocumentRevision, document.active_revision_id or document.candidate_revision_id
    )
    path = request.app.state.settings.upload_dir / revision.storage_key
    if not path.is_file():
        raise AuthError(404, "NOT_FOUND", "原文件不存在")
    return FileResponse(path, filename=revision.filename, media_type="application/octet-stream")
