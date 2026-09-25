from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.permissions import require_roles
from app.modules.auth.schemas import Actor
from app.modules.auth.service import current_actor
from app.modules.knowledge import service
from app.modules.knowledge.models import KnowledgeBase
from app.modules.knowledge.permissions import require_read
from app.modules.knowledge.schemas import (
    FaqCreate,
    FaqPage,
    FaqPatch,
    FaqSummary,
    KnowledgeCreate,
    KnowledgePage,
    KnowledgePatch,
    KnowledgeSummary,
    MembersInput,
    MembersResult,
)

router = APIRouter(prefix="/api/v1", tags=["knowledge"])
Database = Annotated[Session, Depends(get_db)]
CurrentActor = Annotated[Actor, Depends(current_actor)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def admin_actor(actor: CurrentActor):
    require_roles(actor, "admin")
    return actor


Admin = Annotated[Actor, Depends(admin_actor)]


@router.get("/knowledge-bases", response_model=KnowledgePage)
def list_knowledge(db: Database, actor: CurrentActor, page: Page = 1, page_size: PageSize = 20):
    return service.paginate(
        db,
        service.readable_knowledge_bases(actor).order_by(KnowledgeBase.name, KnowledgeBase.id),
        page,
        page_size,
    )


@router.get("/admin/knowledge-bases", response_model=KnowledgePage)
def manage_knowledge(db: Database, actor: Admin, page: Page = 1, page_size: PageSize = 20):
    return service.paginate(
        db,
        select(KnowledgeBase).order_by(KnowledgeBase.name, KnowledgeBase.id),
        page,
        page_size,
    )


@router.post("/knowledge-bases", response_model=KnowledgeSummary, status_code=201)
def create_knowledge(data: KnowledgeCreate, request: Request, db: Database, actor: Admin):
    return service.create_knowledge(db, request, actor, data)


@router.get("/knowledge-bases/{kb_id}", response_model=KnowledgeSummary)
def get_knowledge(kb_id: UUID, db: Database, actor: CurrentActor):
    return require_read(db, actor, kb_id)


@router.patch("/knowledge-bases/{kb_id}", response_model=KnowledgeSummary)
def patch_knowledge(
    kb_id: UUID,
    data: KnowledgePatch,
    request: Request,
    db: Database,
    actor: Admin,
):
    return service.update_knowledge(db, request, actor, kb_id, data)


@router.get("/knowledge-bases/{kb_id}/members", response_model=MembersResult)
def get_members(kb_id: UUID, db: Database, actor: Admin):
    return service.get_members(db, actor, kb_id)


@router.put("/knowledge-bases/{kb_id}/members", response_model=MembersResult)
def put_members(kb_id: UUID, data: MembersInput, request: Request, db: Database, actor: Admin):
    return service.set_members(db, request, actor, kb_id, data)


@router.get("/knowledge-bases/{kb_id}/faqs", response_model=FaqPage)
def get_faqs(
    kb_id: UUID,
    db: Database,
    actor: CurrentActor,
    page: Page = 1,
    page_size: PageSize = 20,
):
    return service.list_faqs(db, actor, kb_id, page, page_size)


@router.post("/knowledge-bases/{kb_id}/faqs", response_model=FaqSummary, status_code=201)
def create_faq(kb_id: UUID, data: FaqCreate, request: Request, db: Database, actor: Admin):
    return service.create_faq(db, request, actor, kb_id, data)


@router.patch("/faqs/{faq_id}", response_model=FaqSummary)
def patch_faq(faq_id: UUID, data: FaqPatch, request: Request, db: Database, actor: Admin):
    return service.update_faq(db, request, actor, faq_id, data)


@router.delete("/faqs/{faq_id}", status_code=204)
def disable_faq(faq_id: UUID, request: Request, db: Database, actor: Admin):
    service.update_faq(db, request, actor, faq_id, None)
