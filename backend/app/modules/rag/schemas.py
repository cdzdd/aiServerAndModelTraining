"""Internal RAG results; citation metadata is supplied only by the server."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RAGError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    index: int
    chunk_id: UUID
    kb_id: UUID
    source_type: Literal["document", "faq"]
    source_id: UUID
    title: str
    quote: str
    revision_id: UUID | None = None
    faq_version: int | None = None
    page_number: int | None = None
    paragraph_number: int | None = None
    line_number: int | None = None


class AnswerEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["delta", "citations", "done", "error"]
    payload: dict
