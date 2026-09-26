from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class QueueItem(BaseModel):
    id: UUID
    conversation_id: UUID
    requested_at: datetime
    state: Literal["queued"] = "queued"


class HandoffView(BaseModel):
    id: UUID
    conversation_id: UUID
    state: Literal["queued", "human", "closed"]
    requested_at: datetime
    claimed_at: datetime | None
    closed_at: datetime | None
    assigned_agent_id: UUID | None


class QueuePage(BaseModel):
    items: list[QueueItem]
    total: int
    page: int
    page_size: int
