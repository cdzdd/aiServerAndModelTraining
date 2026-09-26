from uuid import UUID

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from app.modules.chat.router import CurrentActor, Page, PageSize, require_ready
from app.modules.handoff import service
from app.modules.handoff.schemas import HandoffView, QueuePage

router = APIRouter(prefix="/api/v1")


@router.post("/conversations/{conversation_id}/handoff", response_model=HandoffView)
async def request_handoff(
    conversation_id: UUID, request: Request, response: Response, actor: CurrentActor
):
    require_ready(request)

    def submit():
        with request.app.state.session_factory() as db:
            result = service.request_handoff(
                db, actor, conversation_id, request.state.request_id, request.app.state.chat_clock()
            )
            db.commit()
            return result

    result, created = await run_in_threadpool(submit)
    if created:
        request.app.state.chat_runtime.cancel(conversation_id)
    response.status_code = 201 if created else 200
    return result


@router.get("/handoffs", response_model=QueuePage)
def queue(request: Request, actor: CurrentActor, page: Page = 1, page_size: PageSize = 20):
    with request.app.state.session_factory() as db:
        return service.list_queue(db, actor, page, page_size)


@router.get("/handoffs/{handoff_id}", response_model=HandoffView)
def detail(handoff_id: UUID, request: Request, actor: CurrentActor):
    with request.app.state.session_factory() as db:
        return service.get_handoff(db, actor, handoff_id)


@router.post("/handoffs/{handoff_id}/claim", response_model=HandoffView)
def claim(handoff_id: UUID, request: Request, actor: CurrentActor):
    require_ready(request)
    with request.app.state.session_factory() as db:
        result = service.claim_handoff(
            db, actor, handoff_id, request.state.request_id, request.app.state.chat_clock()
        )
        db.commit()
        return result


@router.post("/handoffs/{handoff_id}/close", response_model=HandoffView)
async def close(handoff_id: UUID, request: Request, actor: CurrentActor):
    require_ready(request)

    def submit():
        with request.app.state.session_factory() as db:
            result = service.close_handoff(
                db, actor, handoff_id, request.state.request_id, request.app.state.chat_clock()
            )
            db.commit()
            return result

    result = await run_in_threadpool(submit)
    request.app.state.chat_runtime.cancel(result.conversation_id)
    return result
