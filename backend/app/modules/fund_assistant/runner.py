"""App-owned tasks share the existing chat slots and authenticated compute queue."""

import asyncio
import logging
import time
from contextlib import aclosing
from datetime import timedelta

from sqlalchemy import delete, select
from starlette.concurrency import run_in_threadpool

from app.core.request_context import log_failure
from app.modules.auth.models import AuthSession
from app.modules.chat import service as chat
from app.modules.compute.context import GenerationScope, bind_scope
from app.modules.fund_assistant import service

logger = logging.getLogger(__name__)


async def run(state, subject, expected_digest, reservation, session_hash, slot):
    started = time.monotonic()
    content, citations, done = "", [], {}
    status, error_code = "failed", "ASSISTANT_UNAVAILABLE"

    def current():
        if service.credential_digest(state.settings) != expected_digest:
            return False
        with state.session_factory() as db:
            service.require_knowledge(db, state.settings.fund_assistant_kb_id)
            service.owned_conversation(
                db, subject, state.settings.fund_assistant_kb_id, reservation.conversation_id
            )
            session = db.scalar(select(AuthSession).where(AuthSession.token_hash == session_hash))
            return (
                session is not None
                and session.expires_at > state.auth_clock()
                and chat.generation_is_current(db, reservation, reservation.actor)
            )

    def finish():
        with state.session_factory.begin() as db:
            chat.finish_generation(
                db,
                reservation,
                status=status,
                content=content,
                citations=citations,
                done=done,
                error_code=error_code,
                latency_ms=int((time.monotonic() - started) * 1000),
                now=state.chat_clock(),
            )
            db.execute(delete(AuthSession).where(AuthSession.token_hash == session_hash))

    scope = GenerationScope(
        conversation_id=reservation.conversation_id,
        assistant_message_id=reservation.assistant_message_id,
        generation_token=reservation.token,
        actor_id=reservation.actor.user_id,
        actor_role=reservation.actor.role,
        session_hash=session_hash,
        deadline=reservation.accepted_at + timedelta(seconds=60),
    )
    try:
        if not await run_in_threadpool(current):
            status, error_code = "cancelled", "ASSISTANT_AUTHORITY_CHANGED"
            return
        with bind_scope(scope):
            async with asyncio.timeout(
                max(0, (scope.deadline - state.chat_clock()).total_seconds())
            ):
                stream = state.fund_assistant_rag.stream_answer(
                    reservation.actor, reservation.kb_ids, reservation.question, reservation.history
                )
                async with aclosing(stream):
                    async for event in stream:
                        if not await run_in_threadpool(current):
                            status, error_code = "cancelled", "ASSISTANT_AUTHORITY_CHANGED"
                            return
                        if event.type == "delta":
                            content += event.payload["text"]
                            if len(content) > 8192:
                                raise ValueError("Answer too large")
                        elif event.type == "citations":
                            citations = event.payload["items"]
                        elif event.type == "done":
                            done, status, error_code = event.payload, "complete", None
                        elif event.type == "error":
                            content, citations = "", []
                            error_code = event.payload.get("code", "ASSISTANT_UNAVAILABLE")
                            break
    except asyncio.CancelledError:
        status, error_code = "cancelled", "ASSISTANT_CANCELLED"
        content, citations = "", []
    except TimeoutError:
        error_code = "ASSISTANT_TIMEOUT"
        content, citations = "", []
    except Exception:
        error_code = "ASSISTANT_UNAVAILABLE"
        content, citations = "", []
    finally:
        if status != "complete":
            content, citations = "", []
        # Finish on cancellation before releasing the slot or disposing the app's database pool.
        task = asyncio.create_task(run_in_threadpool(finish))
        try:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
            task.result()
        except Exception:
            log_failure(
                logger,
                "fund_assistant_finish_failed",
                "ASSISTANT_PERSISTENCE_FAILED",
                request_id=reservation.request_id,
            )
        finally:
            state.chat_runtime.release(reservation.conversation_id, slot)
