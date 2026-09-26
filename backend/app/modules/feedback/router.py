from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.core.database import get_db
from app.modules.auth.schemas import Actor
from app.modules.auth.service import current_actor
from app.modules.feedback import service
from app.modules.feedback.schemas import (
    FeedbackCreate,
    FeedbackDetail,
    FeedbackPage,
    FeedbackPatch,
    FeedbackView,
    Rating,
    ResolutionInput,
    Status,
)

router = APIRouter(prefix="/api/v1", tags=["feedback"])
CurrentActor = Annotated[Actor, Depends(current_actor)]
Database = Annotated[object, Depends(get_db)]


@router.post("/messages/{message_id}/feedback", response_model=FeedbackView, status_code=201)
def submit(
    message_id: UUID,
    data: FeedbackCreate,
    request: Request,
    response: Response,
    actor: CurrentActor,
    db: Database,
):
    row, created = service.submit_feedback(db, actor, message_id, data, request.state.request_id)
    db.commit()
    response.status_code = 201 if created else 200
    return row


@router.get("/messages/{message_id}/feedback", response_model=FeedbackView | None)
def own(message_id: UUID, actor: CurrentActor, db: Database):
    return service.get_own_feedback(db, actor, message_id)


@router.patch("/feedback/{feedback_id}", response_model=FeedbackView)
def edit(
    feedback_id: UUID, data: FeedbackPatch, request: Request, actor: CurrentActor, db: Database
):
    row = service.update_own_feedback(db, actor, feedback_id, data, request.state.request_id)
    db.commit()
    return row


@router.get("/admin/feedback", response_model=FeedbackPage)
def listing(
    actor: CurrentActor,
    db: Database,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Status | None = None,
    rating: Rating | None = None,
):
    return service.list_admin_feedback(db, actor, page, page_size, status, rating)


@router.get("/admin/feedback/{feedback_id}", response_model=FeedbackDetail)
def detail(feedback_id: UUID, actor: CurrentActor, db: Database):
    return service.get_admin_feedback(db, actor, feedback_id)


@router.patch("/admin/feedback/{feedback_id}", response_model=FeedbackView)
def resolve(
    feedback_id: UUID, data: ResolutionInput, request: Request, actor: CurrentActor, db: Database
):
    row = service.resolve_feedback(db, actor, feedback_id, data, request.state.request_id)
    db.commit()
    return row
