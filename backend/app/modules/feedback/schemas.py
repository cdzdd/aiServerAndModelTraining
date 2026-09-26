from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.modules.auth.schemas import valid_text
from app.modules.chat.schemas import MessageView

Rating = Literal["up", "down"]
Status = Literal["open", "resolved"]


def feedback_text(value):
    if not isinstance(value, str):
        raise ValueError("说明必须是文本")
    valid_text(value)
    if value and not value.strip():
        raise ValueError("说明不能仅包含空白")
    return value.strip()


Comment = Annotated[str, BeforeValidator(feedback_text), Field(max_length=2000)]


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Rating
    comment: Comment = ""


class FeedbackPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Rating | None = None
    comment: Comment | None = None

    @model_validator(mode="after")
    def changed_fields(self):
        if not self.model_fields_set or any(
            getattr(self, field) is None for field in self.model_fields_set
        ):
            raise ValueError("至少提供一个非空修改字段")
        return self


class ResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status
    resolution: Comment = ""

    @model_validator(mode="after")
    def resolution_matches_status(self):
        if (self.status == "resolved") != bool(self.resolution):
            raise ValueError("处理完成须提供说明；重新打开时不能保留处理说明")
        return self


class FeedbackView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    message_id: UUID
    conversation_id: UUID
    user_id: UUID
    rating: Rating
    comment: str
    status: Status
    resolution: str
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FeedbackPage(BaseModel):
    items: list[FeedbackView]
    total: int
    page: int
    page_size: int


class FeedbackDetail(BaseModel):
    feedback: FeedbackView
    message_available: bool
    message: MessageView | None
