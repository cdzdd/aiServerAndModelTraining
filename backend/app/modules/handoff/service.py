"""Handoff metadata; Conversation remains the sole state and assignment authority."""

from sqlalchemy import func, select

from app.core.audit import record_audit
from app.core.security import AuthError
from app.modules.chat import service as chat
from app.modules.chat.models import Conversation
from app.modules.handoff.models import Handoff
from app.modules.handoff.schemas import HandoffView, QueueItem, QueuePage


def _missing():
    raise AuthError(404, "NOT_FOUND", "资源不存在或不可见")


def _forbidden():
    raise AuthError(403, "FORBIDDEN", "无权执行此操作")


def _conflict():
    raise AuthError(409, "HANDOFF_STATE_CONFLICT", "会话状态已改变，请刷新后重试")


def _view(handoff, conversation):
    return HandoffView(
        id=handoff.id,
        conversation_id=conversation.id,
        state=conversation.mode,
        requested_at=handoff.requested_at,
        claimed_at=handoff.claimed_at,
        closed_at=handoff.closed_at,
        assigned_agent_id=conversation.assigned_agent_id,
    )


def _audit(db, actor, handoff, action, request_id):
    record_audit(
        db,
        actor_id=actor.user_id,
        action=f"handoff.{action}",
        target_type="handoff",
        target_id=str(handoff.id),
        outcome="success",
        request_id=request_id,
        metadata={"conversation_id": str(handoff.conversation_id)},
    )


def _locked(db, actor, handoff_id):
    chat._current_user(db, actor, lock=True)
    conversation_id = db.scalar(select(Handoff.conversation_id).where(Handoff.id == handoff_id))
    if conversation_id is None:
        _missing()
    conversation = chat._conversation(db, conversation_id, lock=True)
    chat._current_user(db, actor)
    if conversation is None or conversation.deleted_at is not None:
        _missing()
    handoff = db.scalar(
        select(Handoff)
        .where(Handoff.id == handoff_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return handoff, conversation


def request_handoff(db, actor, conversation_id, request_id, now):
    chat._current_user(db, actor, lock=True)
    conversation = chat.get_conversation(db, actor, conversation_id, for_update=True)
    chat._current_user(db, actor)
    if conversation.user_id != actor.user_id:
        _forbidden()
    handoff = db.scalar(
        select(Handoff)
        .where(Handoff.conversation_id == conversation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if conversation.mode in {"queued", "human"}:
        return _view(handoff, conversation), False
    if conversation.mode != "bot":
        _conflict()
    conversation = chat.transition_mode(
        db,
        actor,
        conversation_id,
        expected_mode="bot",
        next_mode="queued",
        assigned_agent_id=None,
        request_id=request_id,
    )
    handoff = Handoff(conversation_id=conversation_id, requested_at=now)
    db.add(handoff)
    db.flush()
    _audit(db, actor, handoff, "request", request_id)
    return _view(handoff, conversation), True


def list_queue(db, actor, page=1, page_size=20):
    chat._current_user(db, actor)
    if actor.role not in {"agent", "admin"}:
        _forbidden()
    query = (
        select(Handoff)
        .join(Conversation)
        .where(Conversation.mode == "queued", Conversation.deleted_at.is_(None))
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(Handoff.requested_at, Handoff.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return QueuePage(
        items=[
            QueueItem(id=row.id, conversation_id=row.conversation_id, requested_at=row.requested_at)
            for row in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_handoff(db, actor, handoff_id):
    chat._current_user(db, actor)
    handoff = db.get(Handoff, handoff_id)
    if handoff is None:
        _missing()
    conversation = chat.get_conversation(db, actor, handoff.conversation_id)
    return _view(handoff, conversation)


def claim_handoff(db, actor, handoff_id, request_id, now):
    chat._current_user(db, actor)
    if actor.role != "agent":
        _forbidden()
    handoff, conversation = _locked(db, actor, handoff_id)
    if conversation.mode != "queued":
        _conflict()
    conversation = chat.transition_mode(
        db,
        actor,
        conversation.id,
        expected_mode="queued",
        next_mode="human",
        assigned_agent_id=actor.user_id,
        request_id=request_id,
    )
    handoff.claimed_at = now
    handoff.claimed_by_id = actor.user_id
    _audit(db, actor, handoff, "claim", request_id)
    return _view(handoff, conversation)


def close_handoff(db, actor, handoff_id, request_id, now):
    handoff, conversation = _locked(db, actor, handoff_id)
    chat.get_conversation(db, actor, conversation.id)
    if actor.role != "admin" and not (
        actor.role == "agent" and conversation.assigned_agent_id == actor.user_id
    ):
        _forbidden()
    if conversation.mode == "closed":
        return _view(handoff, conversation)
    if conversation.mode != "human":
        _conflict()
    conversation = chat.transition_mode(
        db,
        actor,
        conversation.id,
        expected_mode="human",
        next_mode="closed",
        assigned_agent_id=conversation.assigned_agent_id,
        request_id=request_id,
    )
    handoff.closed_at = now
    handoff.closed_by_id = actor.user_id
    _audit(db, actor, handoff, "close", request_id)
    return _view(handoff, conversation)
