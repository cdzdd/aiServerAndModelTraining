from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.security import AuthError
from app.modules.auth.models import User
from app.modules.auth.schemas import Actor
from app.modules.knowledge.models import FAQ, KnowledgeBase, KnowledgeMembership
from app.modules.knowledge.permissions import require_read, visible_condition
from app.modules.knowledge.schemas import (
    FaqCreate,
    FaqPatch,
    KnowledgeCreate,
    KnowledgePatch,
    MembersInput,
)


def readable_knowledge_bases(actor: Actor):
    """Composable SELECT for 006/007; scope is always determined by the authenticated actor."""
    return select(KnowledgeBase).where(visible_condition(actor))


def effective_faqs(actor: Actor, kb_ids: list[UUID]):
    """007 must additionally join version-matching chunks; an empty scope stays empty."""
    return (
        select(FAQ)
        .join(KnowledgeBase)
        .where(
            visible_condition(actor),
            FAQ.kb_id.in_(kb_ids),
            FAQ.is_active.is_(True),
            FAQ.indexed_version == FAQ.version,
        )
    )


def paginate(db: Session, statement, page: int, page_size: int):
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    return {
        "items": db.scalars(statement.offset((page - 1) * page_size).limit(page_size)).all(),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def audit(db: Session, request: Request, actor: Actor, action: str, target, metadata: dict):
    record_audit(
        db,
        actor_id=actor.user_id,
        action=action,
        target_type="faq" if isinstance(target, FAQ) else "knowledge_base",
        target_id=str(target.id),
        outcome="success",
        request_id=request.state.request_id,
        metadata=metadata,
    )


def check_version(actual: int, expected: int):
    if actual != expected:
        raise AuthError(409, "CONFLICT", "内容已被修改，请刷新后重试")


def locked_kb(db: Session, kb_id: UUID, *, active=False):
    kb = db.scalar(
        select(KnowledgeBase)
        .where(KnowledgeBase.id == kb_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if kb is None or (active and not kb.is_active):
        raise AuthError(404, "NOT_FOUND", "资源不存在或不可见")
    return kb


def create_knowledge(db: Session, request: Request, actor: Actor, data: KnowledgeCreate):
    kb = KnowledgeBase(**data.model_dump())
    db.add(kb)
    db.flush()
    audit(db, request, actor, "knowledge.create", kb, {"version": kb.version})
    db.commit()
    return kb


def update_knowledge(
    db: Session, request: Request, actor: Actor, kb_id: UUID, data: KnowledgePatch
):
    kb = locked_kb(db, kb_id)
    check_version(kb.version, data.expected_version)
    changes = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    for key, value in changes.items():
        setattr(kb, key, value)
    kb.version += 1
    audit(
        db,
        request,
        actor,
        "knowledge.update",
        kb,
        {
            "version": kb.version,
            "fields": sorted(changes),
        },
    )
    db.commit()
    return kb


def get_members(db: Session, actor: Actor, kb_id: UUID):
    # Lock against concurrent replacement so the version matches the returned member set.
    kb = locked_kb(db, kb_id, active=True)
    return {
        "user_ids": db.scalars(
            select(KnowledgeMembership.user_id)
            .where(KnowledgeMembership.kb_id == kb_id)
            .order_by(KnowledgeMembership.user_id)
        ).all(),
        "version": kb.version,
    }


def set_members(db: Session, request: Request, actor: Actor, kb_id: UUID, data: MembersInput):
    kb = locked_kb(db, kb_id, active=True)
    check_version(kb.version, data.expected_version)
    count = db.scalar(select(func.count()).select_from(User).where(User.id.in_(data.user_ids)))
    if count != len(data.user_ids):
        raise AuthError(422, "VALIDATION_ERROR", "部分成员账号不存在")
    db.execute(delete(KnowledgeMembership).where(KnowledgeMembership.kb_id == kb_id))
    db.add_all(KnowledgeMembership(kb_id=kb_id, user_id=uid) for uid in data.user_ids)
    kb.version += 1
    audit(
        db,
        request,
        actor,
        "knowledge.members",
        kb,
        {
            "version": kb.version,
            "member_count": len(data.user_ids),
        },
    )
    db.commit()
    return {"user_ids": sorted(data.user_ids), "version": kb.version}


def list_faqs(db: Session, actor: Actor, kb_id: UUID, page: int, page_size: int):
    require_read(db, actor, kb_id)
    statement = select(FAQ).where(FAQ.kb_id == kb_id)
    if actor.role != "admin":
        statement = statement.where(FAQ.is_active.is_(True))
    return paginate(db, statement.order_by(FAQ.updated_at.desc(), FAQ.id), page, page_size)


def create_faq(db: Session, request: Request, actor: Actor, kb_id: UUID, data: FaqCreate):
    locked_kb(db, kb_id, active=True)
    faq = FAQ(kb_id=kb_id, **data.model_dump())
    db.add(faq)
    db.flush()
    audit(db, request, actor, "faq.create", faq, {"kb_id": str(kb_id), "version": faq.version})
    db.commit()
    return faq


def update_faq(
    db: Session,
    request: Request,
    actor: Actor,
    faq_id: UUID,
    data: FaqPatch | None,
):
    # Lock order is always knowledge base then FAQ, including competing disable operations.
    kb_id = db.scalar(select(FAQ.kb_id).where(FAQ.id == faq_id))
    if kb_id is None:
        raise AuthError(404, "NOT_FOUND", "资源不存在或不可见")
    locked_kb(db, kb_id, active=True)
    faq = db.scalar(select(FAQ).where(FAQ.id == faq_id).with_for_update())
    if data is not None:
        check_version(faq.version, data.expected_version)
        changes = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    else:
        if not faq.is_active:
            return faq
        changes = {"is_active": False}
    for key, value in changes.items():
        setattr(faq, key, value)
    faq.version += 1
    faq.updated_at = datetime.now(UTC)
    audit(
        db,
        request,
        actor,
        "faq.disable" if data is None else "faq.update",
        faq,
        {
            "kb_id": str(kb_id),
            "version": faq.version,
            "fields": sorted(changes),
        },
    )
    db.commit()
    return faq
