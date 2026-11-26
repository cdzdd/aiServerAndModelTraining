"""Generate through the bounded compute queue inside a server-owned chat scope."""

import asyncio
from datetime import UTC, datetime

import anyio
from starlette.concurrency import run_in_threadpool

from app.core.security import AuthError
from app.modules.compute import service
from app.modules.compute.context import generation_scope
from app.modules.compute.models import ComputeJob
from app.modules.compute.progress import report_stage

from .base import validate_request
from .errors import MESSAGES, ProviderError
from .schemas import LLMDelta, LLMUsage


class QueuedProvider:
    def __init__(self, session_factory, *, model_id: str, max_output_tokens: int):
        self.session_factory = session_factory
        self.model_id = model_id
        self.max_output_tokens = min(max_output_tokens, 512)

    def _transaction(self, operation, *args):
        with self.session_factory() as db:
            try:
                result = operation(db, *args, now=lambda: datetime.now(UTC))
            except AuthError:
                # Expiry and revocation may mark work terminal before reporting the conflict.
                db.commit()
                raise
            db.commit()
            return result

    def _take_result(self, job_id, scope, *, now):
        with self.session_factory() as db:
            try:
                result = service.take_result(db, job_id, scope, now=now)
            except AuthError:
                db.commit()
                raise
            job = db.get(ComputeJob, job_id)
            running = job is not None and job.status == "running"
            db.commit()
        return result, running

    async def _critical_transaction(self, operation, *args):
        task = asyncio.create_task(run_in_threadpool(self._transaction, operation, *args))
        interrupted = False
        with anyio.CancelScope(shield=True):
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    # AnyIO shielding does not block repeated native Task.cancel() calls.
                    interrupted = True
        return task.result(), interrupted

    async def stream(self, messages, *, max_tokens: int, temperature: float):
        validate_request(messages, max_tokens, temperature, self.max_output_tokens)
        scope = generation_scope.get()
        if scope is None:
            raise ProviderError("PROVIDER_CONFIG_ERROR")
        payload = {
            "model_id": self.model_id,
            "messages": [message.model_dump() for message in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        job_id = None
        consumed = False
        reported_running = False
        try:
            # Retain ownership until enqueue commits and its ID can be cancelled in finally.
            job_id, interrupted = await self._critical_transaction(service.enqueue, scope, payload)
            if interrupted:
                raise asyncio.CancelledError
            report_stage("queued")
            while True:
                if datetime.now(UTC) >= scope.deadline:
                    raise ProviderError("PROVIDER_TIMEOUT")
                result, running = await run_in_threadpool(
                    self._take_result, job_id, scope, now=lambda: datetime.now(UTC)
                )
                if running and not reported_running:
                    report_stage("generating")
                    reported_running = True
                if result is not None:
                    consumed = True
                    yield LLMDelta(
                        text=result["text"],
                        finish_reason=result["finish_reason"],
                        usage=LLMUsage(**result["usage"]) if result["usage"] else None,
                    )
                    return
                await asyncio.sleep(0.1)
        except AuthError as error:
            code = error.code if error.code in MESSAGES else "PROVIDER_UNAVAILABLE"
            if datetime.now(UTC) >= scope.deadline:
                code = "PROVIDER_TIMEOUT"
            raise ProviderError(code) from None
        finally:
            if job_id is not None and not consumed:
                _, interrupted = await self._critical_transaction(service.cancel, job_id)
                if interrupted:
                    raise asyncio.CancelledError
