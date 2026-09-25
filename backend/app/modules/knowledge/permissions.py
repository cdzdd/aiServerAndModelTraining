from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.core.security import AuthError
from app.modules.auth.permissions import require_knowledge_access
from app.modules.auth.schemas import Actor
from app.modules.knowledge.models import KnowledgeBase, KnowledgeMembership


def visible_condition(actor: Actor):
    member = exists().where(
        KnowledgeMembership.kb_id == KnowledgeBase.id,
        KnowledgeMembership.user_id == actor.user_id,
    )
    return KnowledgeBase.is_active.is_(True) & (
        True if actor.role == "admin" else or_(KnowledgeBase.visibility == "public", member)
    )


def require_read(db: Session, actor: Actor, kb_id: UUID) -> KnowledgeBase:
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise AuthError(404, "NOT_FOUND", "资源不存在或不可见")
    member = db.scalar(
        select(
            exists().where(
                KnowledgeMembership.kb_id == kb_id,
                KnowledgeMembership.user_id == actor.user_id,
            )
        )
    )
    require_knowledge_access(
        actor, visibility=kb.visibility, is_member=bool(member), is_active=kb.is_active
    )
    return kb
