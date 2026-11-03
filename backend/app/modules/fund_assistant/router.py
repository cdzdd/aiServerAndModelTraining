import asyncio
from typing import Annotated
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.modules.auth.schemas import clean_display_name
from app.modules.chat import service as chat
from app.modules.chat.schemas import Content
from app.modules.fund_assistant import runner, service

router = APIRouter(prefix="/internal/fund-assistant", tags=["fund-assistant"])
Identity = Annotated[tuple[str, str], Depends(service.authenticate)]


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    title: Annotated[
        str, BeforeValidator(clean_display_name), Field(min_length=1, max_length=50)
    ] = "新会话"


class QuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    content: Content
    requestId: UUID


@router.get("/status")
def status(request: Request, identity: Identity):
    with request.app.state.session_factory() as db:
        return service.status(db, request.app.state)


@router.get("/conversations")
def conversations(request: Request, identity: Identity):
    with request.app.state.session_factory() as db:
        return service.list_conversations(
            db, identity[0], request.app.state.settings.fund_assistant_kb_id
        )


@router.post("/conversations", status_code=201)
def create(data: ConversationInput, request: Request, identity: Identity):
    with request.app.state.session_factory.begin() as db:
        return service.create_conversation(
            db,
            identity[0],
            request.app.state.settings.fund_assistant_kb_id,
            data.title,
            request.state.request_id,
        )


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: UUID, request: Request, identity: Identity):
    with request.app.state.session_factory() as db:
        return service.conversation_view(
            db, identity[0], request.app.state.settings.fund_assistant_kb_id, conversation_id
        )


@router.post("/conversations/{conversation_id}/messages", status_code=202)
async def ask(conversation_id: UUID, data: QuestionInput, request: Request, identity: Identity):
    state = request.app.state
    subject, digest = identity
    kb_id = state.settings.fund_assistant_kb_id

    def preflight():
        with state.session_factory() as db:
            service.require_knowledge(db, kb_id)
            actor, _ = service.owned_conversation(db, subject, kb_id, conversation_id)
            prior = service.prior_request(db, actor, conversation_id, data)
            if prior is None:
                service.require_available(db, state)
            return prior

    prior = await run_in_threadpool(preflight)
    if prior:
        return prior
    slot = state.chat_runtime.reserve(conversation_id)

    def reserve():
        with state.session_factory.begin() as db:
            actor, _ = service.owned_conversation(db, subject, kb_id, conversation_id)
            return service.reserve(
                db, actor, conversation_id, data, request.state.request_id, state
            )

    interrupted = False
    operation = asyncio.create_task(run_in_threadpool(reserve))
    try:
        # A disconnect cannot abandon a committed reservation with no task to settle it.
        with anyio.CancelScope(shield=True):
            while not operation.done():
                try:
                    await asyncio.shield(operation)
                except asyncio.CancelledError:
                    interrupted = True
        reservation, session_hash = operation.result()
    except BaseException:
        state.chat_runtime.release(conversation_id, slot)
        raise
    task = asyncio.create_task(runner.run(state, subject, digest, reservation, session_hash, slot))
    state.chat_runtime.bind(conversation_id, slot, task)
    if interrupted:
        raise asyncio.CancelledError
    return dict(conversationId=str(conversation_id), requestId=str(data.requestId), status="queued")


@router.post("/conversations/{conversation_id}/cancel")
async def cancel(conversation_id: UUID, request: Request, identity: Identity):
    state = request.app.state

    def cancel_transaction():
        with state.session_factory.begin() as db:
            _, conversation = service.owned_conversation(
                db, identity[0], state.settings.fund_assistant_kb_id, conversation_id, lock=True
            )
            chat._cancel_generation(db, conversation, state.chat_clock())

    await run_in_threadpool(cancel_transaction)
    state.chat_runtime.cancel(conversation_id)
    return dict(conversationId=str(conversation_id), status="cancelled")
