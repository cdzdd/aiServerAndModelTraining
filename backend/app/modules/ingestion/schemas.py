from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictBool


class RevisionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    filename: str
    content_sha256: str
    parser_version: str
    created_at: datetime


class JobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    state: str
    attempts: int
    error_code: str | None
    error_message: str | None = None
    created_at: datetime
    finished_at: datetime | None


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kb_id: UUID
    filename: str
    status: str
    active_revision_id: UUID | None
    candidate_revision_id: UUID | None
    created_at: datetime
    active_revision: RevisionSummary | None = None
    candidate_revision: RevisionSummary | None = None
    latest_job: JobSummary | None = None


class DocumentPage(BaseModel):
    items: list[DocumentSummary]
    total: int
    page: int
    page_size: int


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: StrictBool


class UploadResult(BaseModel):
    document_id: UUID
    job_id: UUID
    status: str = "uploaded"


class RetryResult(BaseModel):
    job_id: UUID
