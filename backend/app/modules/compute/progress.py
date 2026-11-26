"""Request-local coarse progress, without model text or durable job metadata."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from contextvars import ContextVar

from app.modules.rag.schemas import AnswerEvent

STAGES = frozenset(
    {"preparing", "rewriting", "retrieving", "queued", "generating", "validating"}
)
_listener: ContextVar[Callable[[str], None] | None] = ContextVar("compute_progress", default=None)


def report_stage(stage: str) -> None:
    if stage not in STAGES:
        raise ValueError("Unknown generation stage")
    listener = _listener.get()
    if listener is not None:
        listener(stage)


async def stream_with_progress(source: AsyncIterator[AnswerEvent]) -> AsyncIterator[AnswerEvent]:
    loop = asyncio.get_running_loop()
    stages: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
    last = None

    def publish(stage):
        nonlocal last
        if stage == last:
            return
        last = stage
        if stages.full():
            stages.get_nowait()
        stages.put_nowait(stage)

    publish("preparing")
    token = _listener.set(lambda stage: loop.call_soon_threadsafe(publish, stage))
    pending = asyncio.create_task(anext(source))
    waiting = asyncio.create_task(stages.get())
    try:
        async with aclosing(source):
            try:
                while True:
                    done, _ = await asyncio.wait(
                        (pending, waiting), return_when=asyncio.FIRST_COMPLETED
                    )
                    if waiting in done:
                        stage = waiting.result()
                        waiting = asyncio.create_task(stages.get())
                        yield AnswerEvent(type="progress", payload={"stage": stage})
                    if pending in done:
                        try:
                            event = pending.result()
                        except StopAsyncIteration:
                            return
                        yield event
                        pending = asyncio.create_task(anext(source))
            finally:
                pending.cancel()
                waiting.cancel()
                await asyncio.gather(pending, waiting, return_exceptions=True)
    finally:
        _listener.reset(token)
