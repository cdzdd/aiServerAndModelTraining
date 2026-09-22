from uuid import UUID

from app.core.security import AuthError
from app.modules.auth.schemas import Actor, Role


def require_roles(actor: Actor, *roles: Role) -> None:
    if actor.role not in roles:
        raise AuthError(403, "FORBIDDEN", "没有访问权限")


def require_conversation_access(
    actor: Actor,
    *,
    owner_id: UUID,
    assigned_agent_id: UUID | None,
) -> None:
    if (
        actor.role == "admin"
        or actor.user_id == owner_id
        or (actor.role == "agent" and actor.user_id == assigned_agent_id)
    ):
        return
    raise AuthError(404, "NOT_FOUND", "资源不存在或不可见")


def require_knowledge_access(
    actor: Actor,
    *,
    visibility: str,
    is_member: bool,
    is_active: bool,
) -> None:
    if is_active and (
        actor.role == "admin"
        or visibility == "public"
        or (visibility == "restricted" and is_member)
    ):
        return
    raise AuthError(404, "NOT_FOUND", "资源不存在或不可见")
