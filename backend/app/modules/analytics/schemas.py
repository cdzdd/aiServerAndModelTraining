from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_serializer

Count = Annotated[int, Field(ge=0)]
Fraction = Annotated[float, Field(ge=0, le=1)]


class RangeView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    start: AwareDatetime = Field(alias="from")
    end: AwareDatetime = Field(alias="to")
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"


class RatioView(BaseModel):
    numerator: Count
    denominator: Count
    value: Fraction | None


class Logins(BaseModel):
    successful: Count


class GenerationStats(BaseModel):
    accepted: Count
    distinct_users: Count
    complete: Count
    failed: Count
    cancelled: Count
    generating: Count
    answered: Count
    clarify: Count
    no_answer: Count
    unclassified_complete: Count
    no_answer_ratio: RatioView


class LatencyStats(BaseModel):
    average_ms: float | None
    sample_count: Count
    missing_count: Count


class TokenFieldStats(BaseModel):
    value: Count | None
    known_sum: Count
    known_count: Count
    missing_count: Count
    coverage: Fraction | None


class CostUnknown(BaseModel):
    amount: None = None
    status: Literal["unknown"] = "unknown"
    reason: str = "缺少逐请求模型价格归属及完整用量，无法计算费用"


class TokenStats(BaseModel):
    terminal_count: Count
    pending_count: Count
    prompt_tokens: TokenFieldStats
    completion_tokens: TokenFieldStats
    total_tokens: TokenFieldStats
    cost: CostUnknown = Field(default_factory=CostUnknown)


class PeriodHandoffs(BaseModel):
    requested: Count
    claimed: Count
    closed: Count


class CurrentHandoffs(BaseModel):
    queued: Count
    human: Count


class HandoffStats(BaseModel):
    period: PeriodHandoffs
    current: CurrentHandoffs


class FeedbackStats(BaseModel):
    total: Count
    up: Count
    down: Count
    open: Count
    resolved: Count
    satisfaction: RatioView


class JobStates(BaseModel):
    queued: Count = 0
    running: Count = 0
    succeeded: Count = 0
    failed: Count = 0


class PeriodJobs(BaseModel):
    parse: JobStates
    index: JobStates


class DocumentStates(BaseModel):
    uploaded: Count = 0
    processing: Count = 0
    parsed: Count = 0
    ready: Count = 0
    failed: Count = 0
    disabled: Count = 0
    deleted: Count = 0


class IngestionStats(BaseModel):
    period_jobs: PeriodJobs
    current_documents: DocumentStates


class DailyStats(BaseModel):
    date: date
    accepted: Count = 0
    complete: Count = 0
    failed: Count = 0
    cancelled: Count = 0
    generating: Count = 0
    no_answer: Count = 0


class PopularQuestion(BaseModel):
    preview: str
    count: Count
    truncated: bool


class StatsView(BaseModel):
    range: RangeView
    as_of: AwareDatetime
    logins: Logins
    generations: GenerationStats
    latency: LatencyStats
    tokens: TokenStats
    handoffs: HandoffStats
    feedback: FeedbackStats
    ingestion: IngestionStats
    daily: list[DailyStats]
    popular_questions: list[PopularQuestion]


class UserChanges(BaseModel):
    role: Literal["user", "agent", "admin"] | None = None
    is_active: bool | None = None


class AuditMetadata(BaseModel):
    conversation_id: UUID | None = None
    kb_id: UUID | None = None
    version: Count | None = None
    member_count: Count | None = None
    fields: list[str] | None = None
    changed_fields: list[str] | None = None
    before: UserChanges | None = None
    after: UserChanges | None = None
    from_mode: Literal["bot", "queued", "human", "closed"] | None = Field(
        default=None, alias="from"
    )
    to_mode: Literal["bot", "queued", "human", "closed"] | None = Field(default=None, alias="to")
    status: Literal["complete", "failed", "cancelled", "generating", "open", "resolved"] | None = (
        None
    )
    rating: Literal["up", "down"] | None = None
    latency_ms: Count | None = None
    error_code: str | None = None

    @model_serializer(mode="wrap")
    def omit_absent_metadata(self, handler):
        values = {key: value for key, value in handler(self).items() if value is not None}
        for key in ("before", "after"):
            if key in values:
                values[key] = {
                    name: value for name, value in values[key].items() if value is not None
                }
        return values


class AuditEventView(BaseModel):
    id: UUID
    actor_id: UUID | None
    action: str
    summary: str
    target_type: str
    target_id: UUID | None
    outcome: str
    request_id: str | None
    created_at: AwareDatetime
    metadata: AuditMetadata


class AuditPage(BaseModel):
    items: list[AuditEventView]
    total: Count
    page: int
    page_size: int
