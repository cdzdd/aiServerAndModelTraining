from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, model_validator

from app.modules.auth.schemas import clean_display_name

Name = Annotated[str, BeforeValidator(clean_display_name), Field(min_length=1, max_length=100)]
Description = Annotated[str, BeforeValidator(clean_display_name), Field(max_length=2000)]
Question = Annotated[str, BeforeValidator(clean_display_name), Field(min_length=1, max_length=500)]
Answer = Annotated[str, BeforeValidator(clean_display_name), Field(min_length=1, max_length=10000)]
Version = Annotated[int, Field(strict=True, ge=1)]
Visibility = Literal["public", "restricted"]


class KnowledgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    description: Description = ""
    visibility: Visibility = "restricted"


class VersionedPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Version

    @model_validator(mode="after")
    def nonempty_nonnull(self):
        changed = self.model_fields_set - {"expected_version"}
        if not changed or any(getattr(self, field) is None for field in changed):
            raise ValueError("至少提供一个非空修改字段")
        return self


class KnowledgePatch(VersionedPatch):
    name: Name | None = None
    description: Description | None = None
    visibility: Visibility | None = None
    is_active: StrictBool | None = None


class MembersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_ids: list[UUID] = Field(max_length=1000)
    expected_version: Version

    @model_validator(mode="after")
    def unique_members(self):
        if len(self.user_ids) != len(set(self.user_ids)):
            raise ValueError("成员不得重复")
        return self


class MembersResult(BaseModel):
    user_ids: list[UUID]
    version: int


class KnowledgeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    description: str
    visibility: Visibility
    is_active: bool
    version: int


class KnowledgePage(BaseModel):
    items: list[KnowledgeSummary]
    total: int
    page: int
    page_size: int


class FaqCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: Question
    answer: Answer
    is_active: StrictBool = True


class FaqPatch(VersionedPatch):
    question: Question | None = None
    answer: Answer | None = None
    is_active: StrictBool | None = None


class FaqSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kb_id: UUID
    question: str
    answer: str
    is_active: bool
    version: int
    indexed_version: int | None
    updated_at: datetime


class FaqPage(BaseModel):
    items: list[FaqSummary]
    total: int
    page: int
    page_size: int
