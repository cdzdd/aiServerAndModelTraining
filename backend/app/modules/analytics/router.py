from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime, BeforeValidator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.analytics import service
from app.modules.analytics.schemas import AuditEventView, AuditPage, RangeView, StatsView
from app.modules.auth.schemas import Actor
from app.modules.auth.service import current_actor

router = APIRouter(prefix="/api/v1/admin", tags=["analytics"])
CurrentActor = Annotated[Actor, Depends(current_actor)]
Database = Annotated[Session, Depends(get_db)]


def iso_datetime(value):
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("时间须为带时区ISO8601格式")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("时间须为带时区ISO8601格式") from None


ISOInstant = Annotated[AwareDatetime, BeforeValidator(iso_datetime)]
Identifier = Annotated[
    str | None, Query(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
]


def period(
    start: Annotated[ISOInstant | None, Query(alias="from")] = None,
    end: Annotated[ISOInstant | None, Query(alias="to")] = None,
):
    return service.make_range(start, end)


@router.get("/stats", response_model=StatsView)
def stats(request: Request, actor: CurrentActor, selected: Annotated[RangeView, Depends(period)]):
    return service.get_stats(request.app.state.session_factory, actor, selected)


@router.get("/audit-events", response_model=AuditPage)
def audits(
    actor: CurrentActor,
    db: Database,
    selected: Annotated[RangeView, Depends(period)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    action: Identifier = None,
    outcome: Annotated[
        str | None, Query(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9_.-]+$")
    ] = None,
    actor_id: UUID | None = None,
    target_type: Annotated[
        str | None, Query(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    ] = None,
    target_id: UUID | None = None,
):
    return service.list_audit_events(
        db,
        actor,
        selected,
        dict(
            action=action,
            outcome=outcome,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
        ),
        page,
        page_size,
    )


@router.get("/audit-events/{event_id}", response_model=AuditEventView)
def audit_detail(event_id: UUID, actor: CurrentActor, db: Database):
    return service.get_audit_event(db, actor, event_id)
