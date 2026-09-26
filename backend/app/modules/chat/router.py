"""Authenticated conversation CRUD and bounded SSE generation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.core.errors import error_response
from app.core.security import AuthError
from app.modules.auth.schemas import Actor
from app.modules.auth.service import find_session
from app.modules.chat import service
from app.modules.chat.models import Message
from app.modules.chat.schemas import (
    ConversationCreate,
    ConversationPage,
    ConversationView,
    MessageInput,
    MessagePage,
    MessageView,
)
from app.modules.chat.streaming import ChatStreamingResponse, GenerationStream

router = APIRouter(prefix="/api/v1")


def actor_for_chat(request: Request):
    with request.app.state.session_factory() as db:
        row = find_session(db, request)
        if row is None:
            raise AuthError(401, "UNAUTHENTICATED", "请先登录")
        return Actor(user_id=row[1].id, role=row[1].role)


CurrentActor = Annotated[Actor, Depends(actor_for_chat)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def require_ready(request):
    if not request.app.state.chat_ready:
        raise AuthError(503, "CHAT_UNAVAILABLE", "会话服务尚未就绪，请稍后重试")


def duplicate_response(request, user_id, assistant_id):
    return error_response(
        request,
        409,
        "DUPLICATE_MESSAGE",
        "该消息已经提交，请刷新历史",
        details=[
            {
                "user_message_id": str(user_id),
                "assistant_message_id": str(assistant_id) if assistant_id else None,
            }
        ],
    )


@router.get("/conversations", response_model=ConversationPage)
def conversations(request: Request, actor: CurrentActor, page: Page = 1, page_size: PageSize = 50):
    with request.app.state.session_factory() as db:
        return service.list_conversations(db, actor, page, page_size)


@router.post("/conversations", status_code=201, response_model=ConversationView)
def create_conversation(data: ConversationCreate, request: Request, actor: CurrentActor):
    require_ready(request)
    with request.app.state.session_factory() as db:
        result = service.create_conversation(db, actor, data.kb_ids, request.state.request_id)
        db.commit()
        return ConversationView.model_validate(result)


@router.get("/conversations/{conversation_id}", response_model=ConversationView)
def conversation(conversation_id: UUID, request: Request, actor: CurrentActor):
    with request.app.state.session_factory() as db:
        return service.get_conversation(db, actor, conversation_id)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: UUID, request: Request, actor: CurrentActor):
    require_ready(request)

    def remove():
        with request.app.state.session_factory() as db:
            service.delete_conversation(
                db, actor, conversation_id, request.state.request_id, request.app.state.chat_clock()
            )
            db.commit()

    await run_in_threadpool(remove)
    request.app.state.chat_runtime.cancel(conversation_id)
    return Response(status_code=204)


@router.get("/conversations/{conversation_id}/messages", response_model=MessagePage)
def messages(
    conversation_id: UUID,
    request: Request,
    actor: CurrentActor,
    page: Page = 1,
    page_size: PageSize = 50,
):
    with request.app.state.session_factory() as db:
        return service.list_messages(db, actor, conversation_id, page, page_size)


@router.post(
    "/conversations/{conversation_id}/messages", status_code=201, response_model=MessageView
)
def text_message(conversation_id: UUID, data: MessageInput, request: Request, actor: CurrentActor):
    require_ready(request)
    with request.app.state.session_factory() as db:
        try:
            result = service.add_text_message(
                db,
                actor,
                conversation_id,
                data.content,
                data.client_message_id,
                request.state.request_id,
            )
            db.commit()
            return MessageView.model_validate(result)
        except service.DuplicateMessage as exc:
            return duplicate_response(request, exc.user_message_id, exc.assistant_message_id)


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: UUID, data: MessageInput, request: Request, actor: CurrentActor
):
    require_ready(request)

    def preflight():
        with request.app.state.session_factory() as db:
            conv = service.get_conversation(db, actor, conversation_id)
            if conv.user_id != actor.user_id:
                raise AuthError(403, "FORBIDDEN", "仅会话本人可发起问答")
            prior = db.scalar(
                select(Message).where(
                    Message.conversation_id == conversation_id,
                    Message.author_id == actor.user_id,
                    Message.client_message_id == data.client_message_id,
                )
            )
            if prior is not None:
                reply = db.scalar(select(Message.id).where(Message.in_reply_to_id == prior.id))
                return duplicate_response(request, prior.id, reply)
        return None

    duplicate = await run_in_threadpool(preflight)
    if duplicate is not None:
        return duplicate
    state = request.app.state
    slot = state.chat_runtime.reserve(conversation_id)

    def reserve():
        with state.session_factory() as db:
            reservation = service.reserve_generation(
                db,
                actor,
                conversation_id,
                data.content,
                data.client_message_id,
                request.state.request_id,
                state.chat_clock,
                requests_per_minute=state.settings.chat_requests_per_minute,
                requests_per_day=state.settings.chat_requests_per_day,
            )
            db.commit()
            return reservation

    try:
        reservation = await run_in_threadpool(reserve)
    except service.DuplicateMessage as exc:
        state.chat_runtime.release(conversation_id, slot)
        return duplicate_response(request, exc.user_message_id, exc.assistant_message_id)
    except BaseException:
        state.chat_runtime.release(conversation_id, slot)
        raise
    return ChatStreamingResponse(GenerationStream(request, reservation), state.chat_runtime, slot)
