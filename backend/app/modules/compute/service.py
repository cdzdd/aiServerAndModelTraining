"""Short caller-owned transactions, without provider/network work.

`now` accepts an aware datetime for fixed historical tests, or a zero-argument clock.
Live callers pass the clock itself so expiry is checked after all blocking locks.
"""

import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import delete, func, select, text

from app.core.security import AuthError, token_hash
from app.modules.auth.models import AuthSession, User
from app.modules.chat.models import Conversation, Message
from app.modules.compute.context import GenerationScope
from app.modules.compute.models import ComputeJob, ComputeWorker
from app.modules.compute.schemas import FailureResult, Payload, SuccessResult, bounded_json

QUEUE_CAPACITY = 16
MAX_METADATA_ROWS = 10000
LIVE_STATES = ("queued", "running", "succeeded")
TimeSource = datetime | Callable[[], datetime]


def _time(now: TimeSource) -> datetime:
    return now() if callable(now) else now


def _lock(db):
    # All queue transitions are short and serialized, including the empty-table capacity check.
    db.execute(text("SELECT pg_advisory_xact_lock(2021, 1)"))


def _conflict(code="COMPUTE_REVOKED"):
    return AuthError(409, code, "计算任务已结束或不可用")


def _row(db, model, identity):
    return db.scalar(
        select(model)
        .where(model.id == identity)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _scope(job):
    return GenerationScope(
        job.conversation_id,
        job.assistant_message_id,
        job.generation_token,
        job.actor_id,
        job.actor_role,
        job.session_hash,
        job.deadline,
    )


def _scope_valid(db, scope, now):
    # Match chat.finish_generation's User -> Conversation ordering. Locks also serialize
    # account/session revocation and browser cancellation with result acceptance/consumption.
    actor = _row(db, User, scope.actor_id)
    session = db.scalar(
        select(AuthSession)
        .where(AuthSession.token_hash == scope.session_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    conversation = _row(db, Conversation, scope.conversation_id)
    message = _row(db, Message, scope.assistant_message_id)
    checked_at = _time(now)
    return bool(
        scope.deadline > checked_at
        and actor is not None
        and actor.is_active
        and actor.role == scope.actor_role
        and session is not None
        and session.user_id == scope.actor_id
        and session.expires_at > checked_at
        and conversation is not None
        and conversation.user_id == scope.actor_id
        and conversation.deleted_at is None
        and conversation.mode == "bot"
        and conversation.generation_token == scope.generation_token
        and message is not None
        and message.conversation_id == conversation.id
        and message.role == "assistant"
        and message.status == "generating"
        and message.generation_token == scope.generation_token
    ), checked_at


def _worker(db, worker_id):
    current = _row(db, ComputeWorker, worker_id)
    if current is None or not current.is_active:
        raise AuthError(401, "COMPUTE_UNAUTHENTICATED", "计算节点认证无效")
    return current


def register_worker(db, *, name: str, model_id: str, now: TimeSource):
    if not name or len(name) > 100 or not model_id or len(model_id) > 200:
        raise AuthError(422, "VALIDATION_ERROR", "计算节点配置无效")
    raw_token = secrets.token_urlsafe(32)
    worker = ComputeWorker(
        name=name,
        model_id=model_id,
        token_hash=token_hash(raw_token),
        is_active=True,
        created_at=_time(now),
    )
    db.add(worker)
    db.flush()
    return worker, raw_token


def authenticate_worker(db, token: str, *, now):
    if not token or len(token) > 128:
        raise AuthError(401, "COMPUTE_UNAUTHENTICATED", "计算节点认证无效")
    worker = db.scalar(
        select(ComputeWorker)
        .where(ComputeWorker.token_hash == token_hash(token), ComputeWorker.is_active.is_(True))
        .execution_options(populate_existing=True)
    )
    if worker is None:
        raise AuthError(401, "COMPUTE_UNAUTHENTICATED", "计算节点认证无效")
    return worker


def _validated(schema, value):
    try:
        bounded_json(value)
        return schema.model_validate(value).model_dump(mode="json")
    except (ValidationError, ValueError, TypeError, OverflowError):
        raise AuthError(422, "VALIDATION_ERROR", "计算数据格式无效") from None


def enqueue(db, scope: GenerationScope, payload: dict, *, now) -> UUID:
    data = _validated(Payload, payload)
    _lock(db)
    cleanup(db, now=now)
    valid, checked_at = _scope_valid(db, scope, now)
    if not valid:
        raise _conflict()
    count = db.scalar(select(func.count()).select_from(ComputeJob))
    queued = db.scalar(
        select(func.count()).select_from(ComputeJob).where(ComputeJob.status == "queued")
    )
    if count >= MAX_METADATA_ROWS or queued >= QUEUE_CAPACITY:
        raise AuthError(429, "COMPUTE_BUSY", "计算队列已满，请稍后重试")
    job = ComputeJob(
        **{key: getattr(scope, key) for key in scope.__dataclass_fields__},
        model_id=data["model_id"],
        payload=data,
        created_at=checked_at,
        status="queued",
    )
    db.add(job)
    db.flush()
    return job.id


def _clear(job, status, now, code=None):
    job.status, job.payload, job.result = status, None, None
    job.error_code, job.finished_at = code, now


def cleanup(db, *, now, recover=False) -> None:
    _lock(db)
    jobs = db.scalars(
        select(ComputeJob)
        .where(ComputeJob.status.in_(LIVE_STATES))
        .order_by(ComputeJob.created_at, ComputeJob.id)
        .execution_options(populate_existing=True)
    ).all()
    for job in jobs:
        worker = _row(db, ComputeWorker, job.worker_id) if job.worker_id else None
        valid, checked_at = (False, _time(now)) if recover else _scope_valid(db, _scope(job), now)
        if not valid:
            _clear(job, "cancelled", checked_at, "COMPUTE_REVOKED")
        elif job.status == "running" and (
            job.lease_until is None
            or job.lease_until <= checked_at
            or worker is None
            or not worker.is_active
        ):
            _clear(job, "failed", checked_at, "COMPUTE_LEASE_EXPIRED")
        elif job.status == "succeeded" and (worker is None or not worker.is_active):
            _clear(job, "cancelled", checked_at, "COMPUTE_REVOKED")
    db.flush()
    db.execute(delete(ComputeJob).where(ComputeJob.created_at < _time(now) - timedelta(hours=24)))


def claim(db, worker, *, now) -> dict | None:
    _lock(db)
    cleanup(db, now=now)
    worker = _worker(db, worker.id)
    active = db.scalar(
        select(ComputeJob.id).where(
            ComputeJob.worker_id == worker.id, ComputeJob.status == "running"
        )
    )
    if active:
        return None
    job = db.scalar(
        select(ComputeJob)
        .where(ComputeJob.status == "queued", ComputeJob.model_id == worker.model_id)
        .order_by(ComputeJob.created_at, ComputeJob.id)
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        return None
    valid, checked_at = _scope_valid(db, _scope(job), now)
    if not valid:
        _clear(job, "cancelled", checked_at, "COMPUTE_REVOKED")
        db.flush()
        return None
    raw_lease = secrets.token_urlsafe(32)
    job.status, job.worker_id = "running", worker.id
    job.lease_hash, job.lease_until = (
        token_hash(raw_lease),
        min(checked_at + timedelta(seconds=15), job.deadline),
    )
    db.flush()
    return {
        "job_id": str(job.id),
        "lease_token": raw_lease,
        "deadline": job.deadline.isoformat(),
        "payload": job.payload,
    }


def _running(db, worker, job_id, lease_token, now):
    job = _row(db, ComputeJob, job_id)
    worker = _worker(db, worker.id)
    if (
        job is None
        or job.worker_id != worker.id
        or job.model_id != worker.model_id
        or not lease_token
        or len(lease_token) > 128
        or job.lease_hash != token_hash(lease_token)
    ):
        raise _conflict()
    valid, checked_at = _scope_valid(db, _scope(job), now)
    if not valid:
        raise _conflict()
    if job.status != "running" or job.lease_until is None or job.lease_until <= checked_at:
        raise _conflict("COMPUTE_LEASE_EXPIRED")
    return job, checked_at


def heartbeat(db, worker, job_id: UUID, lease_token: str, *, now) -> None:
    _lock(db)
    job, checked_at = _running(db, worker, job_id, lease_token, now)
    job.lease_until = min(checked_at + timedelta(seconds=15), job.deadline)
    db.flush()


def submit_result(db, worker, job_id, lease_token, result: dict, *, now) -> None:
    schema = FailureResult if isinstance(result, dict) and "error_code" in result else SuccessResult
    data = _validated(schema, result)
    digest = hashlib.sha256(bounded_json(data)).hexdigest()
    _lock(db)
    job = _row(db, ComputeJob, job_id)
    worker = _worker(db, worker.id)
    if job is not None:
        valid, _ = _scope_valid(db, _scope(job), now)
        if not valid:
            raise _conflict()
    if (
        job is not None
        and job.status in {"succeeded", "failed", "consumed"}
        and job.result_digest == digest
        and job.worker_id == worker.id
        and job.lease_hash == token_hash(lease_token)
    ):
        return
    job, checked_at = _running(db, worker, job_id, lease_token, now)
    if "model_id" in data and data["model_id"] != job.model_id:
        raise AuthError(422, "VALIDATION_ERROR", "计算模型不匹配")
    job.result_digest = digest
    if "error_code" in data:
        _clear(job, "failed", checked_at, data["error_code"])
    else:
        job.status, job.result, job.finished_at = "succeeded", data, checked_at
    db.flush()


def take_result(db, job_id, scope, *, now) -> dict | None:
    _lock(db)
    job = _row(db, ComputeJob, job_id)
    if job is None or _scope(job) != scope:
        raise _conflict()
    worker = _row(db, ComputeWorker, job.worker_id) if job.worker_id else None
    valid, checked_at = _scope_valid(db, scope, now)
    if not valid:
        raise _conflict()
    if job.status in {"queued", "running"}:
        if job.status == "running" and (job.lease_until is None or job.lease_until <= checked_at):
            raise _conflict("COMPUTE_LEASE_EXPIRED")
        return None
    if job.status != "succeeded":
        raise _conflict(job.error_code or "COMPUTE_REVOKED")
    if worker is None or not worker.is_active:
        raise _conflict()
    result = job.result
    _clear(job, "consumed", checked_at)
    db.flush()
    return result


def cancel(db, job_id, *, now) -> None:
    _lock(db)
    job = _row(db, ComputeJob, job_id)
    if job is not None and job.status in LIVE_STATES:
        _clear(job, "cancelled", _time(now), "COMPUTE_REVOKED")
        db.flush()
