"""Feedback transactions; callers commit changes and their audit records together."""

from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core.audit import record_audit
from app.core.security import AuthError
from app.modules.auth.models import User
from app.modules.auth.permissions import require_roles
from app.modules.chat.models import Conversation, Message
from app.modules.chat.service import visible_messages
from app.modules.feedback.models import Feedback
from app.modules.feedback.schemas import FeedbackDetail, FeedbackView

SOURCE_FIELDS = ("chunk_id", "kb_id", "source_type", "source_id", "revision_id", "faq_version")


def _identity(db, actor, *, write=False, admin=False):
    query = select(User).where(User.id == actor.user_id).execution_options(populate_existing=True)
    if write:
        query = query.with_for_update()
    user = db.scalar(query)
    if user is None or not user.is_active or user.role != actor.role:
        raise AuthError(403, "IDENTITY_CHANGED", "账号状态已发生变化，请重新登录")
    if admin:
        require_roles(actor, "admin")


def _missing():
    raise AuthError(404, "NOT_FOUND", "资源不存在或不可见")


def _owned_message(db, actor, message_id, *, write=False):
    message = db.get(Message, message_id)
    if message is None:
        _missing()
    query = select(Conversation).where(Conversation.id == message.conversation_id)
    if write:
        query = query.with_for_update()
    conversation = db.scalar(query.execution_options(populate_existing=True))
    if (
        conversation is None
        or conversation.deleted_at is not None
        or conversation.user_id != actor.user_id
    ):
        _missing()
    db.refresh(message)
    if message.role != "assistant" or message.status != "complete":
        raise AuthError(409, "FEEDBACK_UNAVAILABLE", "只能评价已完成的 AI 回答")
    return message


def _audit(db, actor, row, action, request_id, fields):
    record_audit(
        db,
        actor_id=actor.user_id,
        action=action,
        target_type="feedback",
        target_id=str(row.id),
        outcome="success",
        request_id=request_id,
        metadata={
            "conversation_id": str(row.conversation_id),
            "rating": row.rating,
            "status": row.status,
            "changed_fields": fields,
        },
    )


def get_own_feedback(db, actor, message_id):
    _identity(db, actor)
    _owned_message(db, actor, message_id)
    return db.scalar(
        select(Feedback).where(Feedback.user_id == actor.user_id, Feedback.message_id == message_id)
    )


def submit_feedback(db, actor, message_id, data, request_id):
    _identity(db, actor, write=True)
    message = _owned_message(db, actor, message_id, write=True)
    existing = db.scalar(
        select(Feedback).where(Feedback.user_id == actor.user_id, Feedback.message_id == message_id)
    )
    if existing is not None:
        if existing.rating == data.rating and existing.comment == data.comment:
            return existing, False
        raise AuthError(409, "FEEDBACK_EXISTS", "已有评价，请修改原评价")
    row = Feedback(
        message_id=message.id,
        conversation_id=message.conversation_id,
        user_id=actor.user_id,
        rating=data.rating,
        comment=data.comment,
        source_versions=[
            {field: citation.get(field) for field in SOURCE_FIELDS}
            for citation in message.citations
        ],
    )
    db.add(row)
    db.flush()
    _audit(db, actor, row, "feedback.create", request_id, ["rating", "comment"])
    return row, True


def update_own_feedback(db, actor, feedback_id, data, request_id):
    _identity(db, actor, write=True)
    row = db.get(Feedback, feedback_id)
    if row is None or row.user_id != actor.user_id:
        _missing()
    _owned_message(db, actor, row.message_id, write=True)
    db.refresh(row, with_for_update=True)
    changes = {
        field: value
        for field, value in data.model_dump(exclude_unset=True).items()
        if getattr(row, field) != value
    }
    if not changes:
        return row
    for field, value in changes.items():
        setattr(row, field, value)
    row.status, row.resolution, row.resolved_by, row.resolved_at = "open", "", None, None
    row.updated_at = datetime.now(UTC)
    _audit(db, actor, row, "feedback.update", request_id, sorted(changes))
    return row


def list_admin_feedback(db, actor, page=1, page_size=20, status=None, rating=None):
    _identity(db, actor, admin=True)
    query = select(Feedback)
    if status is not None:
        query = query.where(Feedback.status == status)
    if rating is not None:
        query = query.where(Feedback.rating == rating)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(Feedback.created_at.desc(), Feedback.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return dict(items=list(rows), total=total, page=page, page_size=page_size)


def get_admin_feedback(db, actor, feedback_id):
    _identity(db, actor, admin=True)
    row = db.get(Feedback, feedback_id)
    if row is None:
        _missing()
    conversation = db.get(Conversation, row.conversation_id)
    message = None
    if conversation is not None and conversation.deleted_at is None:
        stored = db.get(Message, row.message_id)
        if stored is not None:
            message = visible_messages(db, actor, [stored])[0]
    return FeedbackDetail(
        feedback=FeedbackView.model_validate(row),
        message_available=message is not None,
        message=message,
    )


def resolve_feedback(db, actor, feedback_id, data, request_id):
    _identity(db, actor, write=True, admin=True)
    row = db.get(Feedback, feedback_id)
    if row is None:
        _missing()
    db.scalar(select(Conversation).where(Conversation.id == row.conversation_id).with_for_update())
    db.refresh(row, with_for_update=True)
    if row.status == data.status and row.resolution == data.resolution:
        return row
    row.status, row.resolution = data.status, data.resolution
    row.updated_at = datetime.now(UTC)
    row.resolved_by = actor.user_id if data.status == "resolved" else None
    row.resolved_at = row.updated_at if data.status == "resolved" else None
    _audit(
        db,
        actor,
        row,
        "feedback.resolve" if data.status == "resolved" else "feedback.reopen",
        request_id,
        ["status", "resolution"],
    )
    return row
