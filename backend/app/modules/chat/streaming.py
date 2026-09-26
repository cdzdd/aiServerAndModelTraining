"""SSE output owns cancellation and uses short, fresh authorization transactions."""

import asyncio
import json
import logging
import time
from contextlib import aclosing

import anyio
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from app.core.request_context import log_failure
from app.modules.auth.schemas import Actor
from app.modules.auth.service import find_session
from app.modules.chat import service

logger = logging.getLogger(__name__)


def encode_event(kind, payload):
    return f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def failure(code="GENERATION_FAILED"):
    return encode_event("error", {"code": code, "message": "回答未能完成，请刷新历史后重试。"})


class GenerationStream:
    def __init__(self, request, reservation):
        self.request = request
        self.reservation = reservation
        self.state = request.app.state
        self.content = ""
        self.citations = []
        self.finished = False
        self.started = time.monotonic()

    def _current(self):
        with self.state.session_factory() as db:
            row = find_session(db, self.request)
            if row is None:
                return False
            user = row[1]
            return service.generation_is_current(
                db, self.reservation, Actor(user_id=user.id, role=user.role)
            )

    def _finish(self, status, *, done=None, error_code=None):
        requested = status
        with self.state.session_factory() as db:
            if status == "complete" and find_session(db, self.request) is None:
                status, error_code = "cancelled", "AUTHORITY_CHANGED"
            saved = service.finish_generation(
                db,
                self.reservation,
                status=status,
                content=self.content,
                citations=self.citations,
                done=done or {},
                error_code=error_code,
                latency_ms=int((time.monotonic() - self.started) * 1000),
                now=self.state.chat_clock(),
            )
            db.commit()
        self.finished = True
        return saved and status == requested

    async def events(self):
        pending_text = ""
        citations_bound = False
        try:
            if not await run_in_threadpool(self._current):
                await run_in_threadpool(self._finish, "cancelled", error_code="AUTHORITY_CHANGED")
                yield failure("AUTHORITY_CHANGED")
                return
            yield encode_event(
                "meta",
                {
                    "user_message_id": str(self.reservation.user_message_id),
                    "assistant_message_id": str(self.reservation.assistant_message_id),
                },
            )
            result = self.state.chat_rag.stream_answer(
                self.reservation.actor,
                self.reservation.kb_ids,
                self.reservation.question,
                self.reservation.history,
            )
            async with aclosing(result):
                async for event in result:
                    if not await run_in_threadpool(self._current):
                        await run_in_threadpool(
                            self._finish, "cancelled", error_code="AUTHORITY_CHANGED"
                        )
                        yield failure("AUTHORITY_CHANGED")
                        return
                    if event.type == "delta":
                        if citations_bound:
                            raise ValueError("Text arrived after source binding")
                        pending_text += event.payload["text"]
                        continue
                    elif event.type == "citations":
                        if citations_bound:
                            raise ValueError("Repeated source binding")
                        # Bind before exposing text, including persistence on a mid-stream cancel.
                        self.citations = event.payload["items"]
                        self.content = pending_text
                        citations_bound = True
                        if self.content:
                            yield encode_event("delta", {"text": self.content})
                        if not await run_in_threadpool(self._current):
                            await run_in_threadpool(
                                self._finish, "cancelled", error_code="AUTHORITY_CHANGED"
                            )
                            yield failure("AUTHORITY_CHANGED")
                            return
                    elif event.type == "done":
                        if not citations_bound:
                            raise ValueError("Completion arrived before source binding")
                        saved = await run_in_threadpool(
                            self._finish, "complete", done=event.payload
                        )
                        yield (
                            encode_event("done", event.payload)
                            if saved
                            else failure("AUTHORITY_CHANGED")
                        )
                        return
                    elif event.type == "error":
                        await run_in_threadpool(
                            self._finish, "failed", error_code=event.payload["code"]
                        )
                        yield encode_event("error", event.payload)
                        return
                    else:
                        raise ValueError("Unexpected RAG event")
                    yield encode_event(event.type, event.payload)
            await run_in_threadpool(self._finish, "failed", error_code="INCOMPLETE_STREAM")
            yield failure("INCOMPLETE_STREAM")
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self.finished:
                try:
                    await run_in_threadpool(self._finish, "failed", error_code="GENERATION_FAILED")
                except Exception:
                    log_failure(
                        logger,
                        "chat_finalization_failed",
                        "CHAT_FINALIZATION_FAILED",
                        request_id=self.reservation.request_id,
                    )
            yield failure()

    async def close(self):
        if not self.finished:
            try:
                await run_in_threadpool(self._finish, "cancelled", error_code="CANCELLED")
            except Exception:
                # Startup recovery owns any row whose terminal transaction could not commit.
                log_failure(
                    logger,
                    "chat_cancellation_persistence_failed",
                    "CHAT_CANCELLATION_PERSISTENCE_FAILED",
                    request_id=self.reservation.request_id,
                )


class ChatStreamingResponse(StreamingResponse):
    """Listen for disconnects even when ASGI 2.4+ has no pending body send."""

    def __init__(self, generation, runtime, slot):
        self.generation, self.runtime, self.slot = generation, runtime, slot
        super().__init__(
            generation.events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    async def __call__(self, scope, receive, send):
        cid = self.generation.reservation.conversation_id
        async with anyio.create_task_group() as group:

            async def produce():
                self.runtime.bind(cid, self.slot, asyncio.current_task())
                try:
                    await self.stream_response(send)
                except OSError:
                    pass
                finally:
                    with anyio.CancelScope(shield=True):
                        try:
                            await self.body_iterator.aclose()
                        except Exception:
                            log_failure(
                                logger,
                                "chat_stream_close_failed",
                                "CHAT_STREAM_CLOSE_FAILED",
                                request_id=self.generation.reservation.request_id,
                            )
                        finally:
                            try:
                                await self.generation.close()
                            finally:
                                self.runtime.release(cid, self.slot)
                    group.cancel_scope.cancel()

            group.start_soon(produce)
            try:
                await self.listen_for_disconnect(receive)
            finally:
                group.cancel_scope.cancel()
