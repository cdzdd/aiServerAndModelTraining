"""Short, caller-owned transactions for conversations and generation reservations."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import and_, exists, func, or_, select

from app.core.audit import record_audit
from app.core.security import AuthError
from app.modules.auth.models import User
from app.modules.auth.permissions import require_conversation_access
from app.modules.chat.limits import check_budget
from app.modules.chat.models import Conversation, GenerationUsage, Message
from app.modules.chat.schemas import (
    ConversationCreate,
    GenerationReservation,
    MessageInput,
    MessageView,
)
from app.modules.ingestion.models import Chunk
from app.modules.knowledge.service import readable_knowledge_bases
from app.modules.providers.schemas import LLMMessage
from app.modules.rag.schemas import Citation
from app.modules.retrieval.repository import active_candidates

HIDDEN_EVIDENCE = "该回答所依据的资料当前不可访问"


class DuplicateMessage(AuthError):
    def __init__(self, user_message_id, assistant_message_id):
        super().__init__(409, "DUPLICATE_MESSAGE", "此消息已提交，请刷新历史")
        self.user_message_id = user_message_id
        self.assistant_message_id = assistant_message_id


def _current_user(db, actor, *, lock=False):
    query = select(User).where(User.id == actor.user_id).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    user = db.scalar(query)
    if user is None or not user.is_active or user.role != actor.role:
        raise AuthError(403, "IDENTITY_CHANGED", "账号状态已发生变化，请重新登录")
    return user


def _conversation(db, conversation_id, *, lock=False):
    query = (
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def get_conversation(db, actor, conversation_id, *, for_update=False):
    _current_user(db, actor)
    conversation = _conversation(db, conversation_id, lock=for_update)
    if conversation is None or conversation.deleted_at is not None:
        raise AuthError(404, "NOT_FOUND", "资源不存在或不可见")
    require_conversation_access(
        actor, owner_id=conversation.user_id, assigned_agent_id=conversation.assigned_agent_id
    )
    if (
        actor.role != "admin"
        and actor.user_id != conversation.user_id
        and conversation.mode not in {"human", "closed"}
    ):
        raise AuthError(404, "NOT_FOUND", "资源不存在或不可见")
    return conversation


def get_message(db, actor, message_id):
    message = db.get(Message, message_id)
    if message is None:
        raise AuthError(404, "NOT_FOUND", "资源不存在或不可见")
    get_conversation(db, actor, message.conversation_id)
    return message


def _page(db, query, page, page_size):
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    return dict(
        items=list(db.scalars(query.offset((page - 1) * page_size).limit(page_size))),
        total=total,
        page=page,
        page_size=page_size,
    )


def list_conversations(db, actor, page=1, page_size=50):
    _current_user(db, actor)
    query = select(Conversation).where(Conversation.deleted_at.is_(None))
    if actor.role != "admin":
        query = query.where(
            or_(
                Conversation.user_id == actor.user_id,
                and_(
                    actor.role == "agent",
                    Conversation.assigned_agent_id == actor.user_id,
                    Conversation.mode.in_(["human", "closed"]),
                ),
            )
        )
    return _page(
        db, query.order_by(Conversation.updated_at.desc(), Conversation.id), page, page_size
    )


def _audit(db, actor_id, action, conversation, request_id, metadata=None):
    record_audit(
        db,
        actor_id=actor_id,
        action=action,
        target_type="conversation",
        target_id=str(conversation.id),
        outcome="success",
        request_id=request_id,
        metadata=metadata or {},
    )


def create_conversation(db, actor, kb_ids, request_id):
    _current_user(db, actor)
    try:
        ids = ConversationCreate(kb_ids=kb_ids).kb_ids
    except ValidationError:
        raise AuthError(422, "VALIDATION_ERROR", "请选择有效且不重复的知识库") from None
    from app.modules.knowledge.models import KnowledgeBase

    visible = db.scalars(readable_knowledge_bases(actor).where(KnowledgeBase.id.in_(ids))).all()
    if len(visible) != len(ids):
        raise AuthError(404, "NOT_FOUND", "资源不存在或不可见")
    conversation = Conversation(user_id=actor.user_id, kb_ids=[str(value) for value in ids])
    db.add(conversation)
    db.flush()
    _audit(db, actor.user_id, "conversation.create", conversation, request_id)
    return conversation


def _duplicate(db, conversation_id, actor, client_message_id):
    existing = db.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.author_id == actor.user_id,
            Message.client_message_id == client_message_id,
        )
    )
    if existing is not None:
        assistant = db.scalar(select(Message.id).where(Message.in_reply_to_id == existing.id))
        raise DuplicateMessage(existing.id, assistant)


def _message_time(db, conversation_id, now):
    latest = db.scalar(
        select(func.max(Message.created_at)).where(Message.conversation_id == conversation_id)
    )
    return now if latest is None else max(now, latest + timedelta(microseconds=1))


def _input(content, client_message_id):
    try:
        return MessageInput(content=content, client_message_id=client_message_id)
    except ValidationError:
        raise AuthError(422, "VALIDATION_ERROR", "请输入1至2000个有效字符和消息标识") from None


def add_text_message(db, actor, conversation_id, content, client_message_id, request_id):
    data = _input(content, client_message_id)
    _current_user(db, actor, lock=True)
    conversation = get_conversation(db, actor, conversation_id, for_update=True)
    _duplicate(db, conversation_id, actor, data.client_message_id)
    owner = actor.user_id == conversation.user_id
    assignee = actor.role == "agent" and actor.user_id == conversation.assigned_agent_id
    if not owner and not assignee:
        raise AuthError(403, "FORBIDDEN", "不能代替他人发送消息")
    if conversation.mode not in {"queued", "human"} or (not owner and conversation.mode != "human"):
        raise AuthError(409, "CONVERSATION_STATE", "当前会话不能发送人工留言")
    timestamp = _message_time(db, conversation_id, datetime.now(UTC))
    message = Message(
        conversation_id=conversation_id,
        role="user" if owner else "agent",
        author_id=actor.user_id,
        content=data.content,
        client_message_id=data.client_message_id,
        request_id=request_id,
        created_at=timestamp,
    )
    db.add(message)
    conversation.updated_at = timestamp
    db.flush()
    return message


def visible_messages(db, actor, messages):
    _current_user(db, actor)
    parsed, all_citations = {}, []
    for message in messages:
        if message.role == "assistant" and message.citations:
            try:
                parsed[message.id] = [Citation.model_validate(value) for value in message.citations]
                all_citations.extend(parsed[message.id])
            except (ValidationError, TypeError):
                parsed[message.id] = None
    current = {}
    if all_citations:
        query = active_candidates(actor, list({item.kb_id for item in all_citations})).where(
            Chunk.id.in_([item.chunk_id for item in all_citations]),
            exists().where(
                User.id == actor.user_id, User.is_active.is_(True), User.role == actor.role
            ),
        )
        current = {chunk.id: chunk for chunk in db.scalars(query)}
    fields = (
        "kb_id",
        "title",
        "revision_id",
        "faq_version",
        "page_number",
        "paragraph_number",
        "line_number",
    )
    result = []
    for message in messages:
        hidden = message.id in parsed and parsed[message.id] is None
        for citation in parsed.get(message.id) or []:
            chunk = current.get(citation.chunk_id)
            if (
                chunk is None
                or citation.source_id != (chunk.document_id or chunk.faq_id)
                or citation.source_type != ("document" if chunk.document_id else "faq")
                or not citation.quote
                or citation.quote not in chunk.text
                or any(getattr(citation, name) != getattr(chunk, name) for name in fields)
            ):
                hidden = True
        values = {
            name: getattr(message, name)
            for name in MessageView.model_fields
            if name != "evidence_hidden"
        }
        if hidden:
            values.update(content=HIDDEN_EVIDENCE, citations=[])
        values["evidence_hidden"] = hidden
        result.append(MessageView.model_validate(values))
    return result


def list_messages(db, actor, conversation_id, page=1, page_size=50):
    get_conversation(db, actor, conversation_id)
    result = _page(
        db,
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id),
        page,
        page_size,
    )
    result["items"] = visible_messages(db, actor, result["items"])
    return result


def _history(db, actor, conversation_id):
    # Bound both memory and disclosure to the most recent three completed pairs.
    assistants = list(
        db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.status == "complete",
                Message.role == "assistant",
                Message.in_reply_to_id.is_not(None),
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(3)
        )
    )
    users = {
        message.id: message
        for message in db.scalars(
            select(Message).where(
                Message.id.in_([message.in_reply_to_id for message in assistants]),
                Message.conversation_id == conversation_id,
                Message.role == "user",
                Message.status == "complete",
            )
        )
    }
    history = []
    for view in visible_messages(db, actor, list(reversed(assistants))):
        user = users.get(view.in_reply_to_id)
        if not view.evidence_hidden and user is not None:
            history.extend(
                [
                    LLMMessage(role="user", content=user.content),
                    LLMMessage(role="assistant", content=view.content),
                ]
            )
    return history


def reserve_generation(
    db,
    actor,
    conversation_id,
    content,
    client_message_id,
    request_id,
    now,
    *,
    requests_per_minute=10,
    requests_per_day=60,
):
    data = _input(content, client_message_id)
    _current_user(db, actor, lock=True)
    conversation = get_conversation(db, actor, conversation_id, for_update=True)
    if actor.user_id != conversation.user_id:
        raise AuthError(403, "FORBIDDEN", "只能在自己的会话中提问")
    _duplicate(db, conversation_id, actor, data.client_message_id)
    if conversation.mode != "bot":
        raise AuthError(409, "CONVERSATION_STATE", "当前会话不允许AI回答")
    if conversation.generation_token is not None:
        raise AuthError(409, "GENERATION_IN_PROGRESS", "此会话正在回答，请稍候")
    # HTTP supplies the clock, sampled only after the user's serialization lock.
    now = now() if callable(now) else now
    check_budget(
        db,
        actor.user_id,
        now,
        requests_per_minute=requests_per_minute,
        requests_per_day=requests_per_day,
    )
    history = _history(db, actor, conversation_id)
    token = uuid4()
    timestamp = _message_time(db, conversation_id, now)
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        author_id=actor.user_id,
        content=data.content,
        client_message_id=data.client_message_id,
        request_id=request_id,
        created_at=timestamp,
    )
    db.add(user_message)
    db.flush()
    assistant = Message(
        conversation_id=conversation_id,
        role="assistant",
        status="generating",
        in_reply_to_id=user_message.id,
        generation_token=token,
        request_id=request_id,
        created_at=timestamp + timedelta(microseconds=1),
    )
    db.add(assistant)
    db.flush()
    db.add(
        GenerationUsage(
            user_id=actor.user_id,
            conversation_id=conversation_id,
            user_message_id=user_message.id,
            assistant_message_id=assistant.id,
            accepted_at=now,
        )
    )
    if conversation.title == "新会话":
        conversation.title = data.content[:50]
    conversation.generation_token = token
    conversation.updated_at = timestamp
    _audit(db, actor.user_id, "generation.accept", conversation, request_id)
    db.flush()
    return GenerationReservation(
        conversation_id,
        user_message.id,
        assistant.id,
        token,
        actor,
        [UUID(value) for value in conversation.kb_ids],
        data.content,
        history,
        now,
        request_id,
    )


def generation_is_current(db, reservation, current_actor):
    if current_actor != reservation.actor:
        return False
    user = db.scalar(
        select(User).where(
            User.id == current_actor.user_id,
            User.is_active.is_(True),
            User.role == current_actor.role,
        )
    )
    if user is None:
        return False
    return (
        db.scalar(
            select(Message.id)
            .join(Conversation)
            .where(
                Conversation.id == reservation.conversation_id,
                Conversation.user_id == current_actor.user_id,
                Conversation.deleted_at.is_(None),
                Conversation.mode == "bot",
                Conversation.generation_token == reservation.token,
                Message.id == reservation.assistant_message_id,
                Message.status == "generating",
                Message.generation_token == reservation.token,
            )
        )
        is not None
    )


def _settle(db, message, status, now, *, usage=None):
    entry = db.scalar(
        select(GenerationUsage).where(GenerationUsage.assistant_message_id == message.id)
    )
    if entry is not None:
        entry.finished_at, entry.outcome = now, status
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            setattr(entry, field, usage.get(field) if usage else None)
    return entry


def _record_terminal(db, message, conversation, actor_id):
    _audit(
        db,
        actor_id,
        "generation.finish",
        conversation,
        message.request_id,
        {
            "status": message.status,
            "latency_ms": message.latency_ms,
            "error_code": message.error_code,
        },
    )


def _end_without_executor(db, message, conversation, status, reason, now):
    message.status, message.error_code = status, reason
    usage = _settle(db, message, status, now)
    started = usage.accepted_at if usage is not None else message.created_at
    message.latency_ms = max(0, int((now - started).total_seconds() * 1000))
    _record_terminal(db, message, conversation, conversation.user_id)


def finish_generation(
    db, reservation, *, status, content, citations, done, error_code, latency_ms, now
):
    if status not in {"complete", "failed", "cancelled"}:
        raise ValueError("Invalid terminal status")
    db.scalar(select(User).where(User.id == reservation.actor.user_id).with_for_update())
    conversation = _conversation(db, reservation.conversation_id, lock=True)
    message = db.get(Message, reservation.assistant_message_id)
    if (
        conversation is None
        or message is None
        or message.status != "generating"
        or message.generation_token != reservation.token
    ):
        return False
    current = generation_is_current(db, reservation, reservation.actor)
    final_status = status if current else "cancelled"
    message.status = final_status
    message.content, message.citations = content, citations
    message.error_code = error_code if current else "GENERATION_REVOKED"
    message.latency_ms = latency_ms
    if final_status == "complete":
        message.answer_status = done.get("answer_status")
        message.evidence_level = done.get("evidence_level")
        message.intent = done.get("intent")
    _settle(db, message, final_status, now, usage=done.get("usage") if done else None)
    if conversation.generation_token == reservation.token:
        conversation.generation_token = None
    conversation.updated_at = now
    _record_terminal(db, message, conversation, reservation.actor.user_id)
    db.flush()
    return current


def _cancel_generation(db, conversation, now):
    if conversation.generation_token is None:
        return
    message = db.scalar(
        select(Message).where(
            Message.conversation_id == conversation.id,
            Message.status == "generating",
            Message.generation_token == conversation.generation_token,
        )
    )
    if message is not None:
        _end_without_executor(db, message, conversation, "cancelled", "GENERATION_REVOKED", now)
    conversation.generation_token = None


def delete_conversation(db, actor, conversation_id, request_id, now):
    conversation = get_conversation(db, actor, conversation_id, for_update=True)
    if actor.user_id != conversation.user_id and actor.role != "admin":
        raise AuthError(403, "FORBIDDEN", "不能删除他人的会话")
    conversation.deleted_at = now
    _cancel_generation(db, conversation, now)
    _audit(db, actor.user_id, "conversation.delete", conversation, request_id)
    db.flush()


def transition_mode(
    db, actor, conversation_id, *, expected_mode, next_mode, assigned_agent_id, request_id
):
    _current_user(db, actor)
    conversation = _conversation(db, conversation_id, lock=True)
    if conversation is None or conversation.deleted_at is not None:
        raise AuthError(404, "NOT_FOUND", "资源不存在或不可见")
    if conversation.mode != expected_mode:
        raise AuthError(409, "CONVERSATION_STATE", "会话状态已变化，请刷新")
    allowed = (
        (
            expected_mode == "bot"
            and next_mode == "queued"
            and actor.user_id == conversation.user_id
            and assigned_agent_id is None
        )
        or (
            expected_mode == "queued"
            and next_mode == "human"
            and actor.role == "agent"
            and assigned_agent_id == actor.user_id
        )
        or (
            expected_mode == "human"
            and next_mode == "closed"
            and (
                actor.role == "admin"
                or (actor.role == "agent" and actor.user_id == conversation.assigned_agent_id)
            )
            and assigned_agent_id == conversation.assigned_agent_id
        )
    )
    if not allowed:
        raise AuthError(403, "FORBIDDEN", "不允许此会话状态变更")
    now = datetime.now(UTC)
    _cancel_generation(db, conversation, now)
    conversation.mode, conversation.assigned_agent_id = next_mode, assigned_agent_id
    conversation.updated_at = now
    _audit(
        db,
        actor.user_id,
        "conversation.transition",
        conversation,
        request_id,
        {"from": expected_mode, "to": next_mode},
    )
    db.flush()
    return conversation


def recover_generations(session_factory, now):
    with session_factory() as db:
        pending = list(db.scalars(select(Message).where(Message.status == "generating")))
        for message in pending:
            conversation = _conversation(db, message.conversation_id, lock=True)
            _end_without_executor(db, message, conversation, "failed", "PROCESS_RESTARTED", now)
            if conversation.generation_token == message.generation_token:
                conversation.generation_token = None
            _audit(
                db,
                None,
                "generation.recover",
                conversation,
                message.request_id,
                {"status": "failed"},
            )
        db.commit()
        return len(pending)
