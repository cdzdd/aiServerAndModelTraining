"""Stable internal retrieval results and safe caller-facing failures."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SearchHit(BaseModel):
    model_config = ConfigDict(frozen=True)
    chunk_id: UUID
    kb_id: UUID
    text: str
    source_type: Literal["document", "faq"]
    source_id: UUID
    title: str
    score: float
    page_number: int | None = None
    revision_id: UUID | None = None
    faq_version: int | None = None
    paragraph_number: int | None = None
    line_number: int | None = None


class RetrievalError(Exception):
    """Error codes contain no source text, model output or storage details."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
