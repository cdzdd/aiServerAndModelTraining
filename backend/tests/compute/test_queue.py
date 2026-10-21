from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.core.security import AuthError, token_hash
from app.modules.auth.models import AuthSession, User
from app.modules.chat.models import Conversation, Message


@pytest.fixture
def factory(migrated_engine):
    return sessionmaker(migrated_engine, expire_on_commit=False)


@pytest.fixture
def current_time():
    return datetime.now(UTC)


def new_scope(db, now):
    from app.modules.compute.context import GenerationScope

    user = User(username=uuid4().hex, display_name="Test", password_hash="unused", role="user")
    db.add(user)
    db.flush()
    session = AuthSession(
        user_id=user.id,
        token_hash=token_hash(uuid4().hex),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    conversation = Conversation(user_id=user.id, kb_ids=[], generation_token=uuid4())
    db.add_all([session, conversation])
    db.flush()
    message = Message(
        conversation_id=conversation.id,
        role="assistant",
        status="generating",
        generation_token=conversation.generation_token,
        request_id="compute-test",
    )
    db.add(message)
    db.flush()
    return GenerationScope(
        conversation.id,
        message.id,
        conversation.generation_token,
        user.id,
        user.role,
        session.token_hash,
        now + timedelta(seconds=60),
    )


def payload():
    return {
        "model_id": "test-model",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 512,
        "temperature": 0.2,
    }


def result(text="answer"):
    return {"model_id": "test-model", "text": text, "finish_reason": "stop", "usage": None}


@pytest.fixture
def setup_job(factory, current_time):
    from app.modules.compute import service
    from app.modules.compute.models import ComputeJob

    with factory.begin() as db:
        # Rows from another test cannot consume the fixed capacity / single-worker lease.
        db.execute(delete(ComputeJob))
        scope = new_scope(db, current_time)
        worker, token = service.register_worker(
            db, name="desktop", model_id="test-model", now=current_time
        )
        job_id = service.enqueue(db, scope, payload(), now=current_time)
    return scope, worker, token, job_id


def test_feature_exists():
    from app.modules.compute import service

    assert callable(service.enqueue)


def test_hashed_credential_and_caller_transaction(factory, current_time):
    from app.modules.compute import service
    from app.modules.compute.models import ComputeWorker

    with factory() as db:
        worker, raw = service.register_worker(
            db, name="desktop", model_id="test-model", now=current_time
        )
        assert worker.token_hash == token_hash(raw)
        assert raw not in repr(worker.__dict__)
        worker_id = worker.id
        db.rollback()
    with factory() as db:
        assert db.get(ComputeWorker, worker_id) is None
        with pytest.raises(AuthError) as exc:
            service.authenticate_worker(db, raw, now=current_time)
        assert exc.value.status == 401


def test_single_atomic_claim_and_single_consumption(factory, current_time, setup_job):
    from app.modules.compute import service
    from app.modules.compute.models import ComputeJob

    scope, worker, _, job_id = setup_job

    def claim():
        with factory.begin() as db:
            return service.claim(db, worker, now=current_time)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim(), range(2)))
    claim_data = next(value for value in claims if value)
    assert len([value for value in claims if value]) == 1
    assert claim_data["job_id"] == str(job_id)
    with factory.begin() as db:
        service.submit_result(
            db, worker, job_id, claim_data["lease_token"], result(), now=current_time
        )
        service.submit_result(
            db, worker, job_id, claim_data["lease_token"], result(), now=current_time
        )
        with pytest.raises(AuthError):
            service.submit_result(
                db, worker, job_id, claim_data["lease_token"], result("changed"), now=current_time
            )
    with factory.begin() as db:
        assert service.take_result(db, job_id, scope, now=current_time) == result()
        with pytest.raises(AuthError):
            service.take_result(db, job_id, scope, now=current_time)
        job = db.get(ComputeJob, job_id)
        assert job.payload is None and job.result is None


def test_queue_capacity_is_serialized(factory, current_time, setup_job):
    from app.modules.compute import service

    with factory.begin() as db:
        for _ in range(14):
            service.enqueue(db, new_scope(db, current_time), payload(), now=current_time)

    def enqueue():
        try:
            with factory.begin() as db:
                service.enqueue(db, new_scope(db, current_time), payload(), now=current_time)
            return "accepted"
        except AuthError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: enqueue(), range(2)))
    assert results.count("accepted") == 1 and results.count(429) == 1


@pytest.mark.parametrize(
    "expiry",
    ["lease", "deadline", "actor", "role", "session", "generation", "deleted", "mode", "worker"],
)
def test_expired_or_revoked_work_never_accepts_result(factory, current_time, setup_job, expiry):
    from app.modules.compute import service
    from app.modules.compute.models import ComputeJob, ComputeWorker

    scope, worker, _, job_id = setup_job
    with factory.begin() as db:
        claim = service.claim(db, worker, now=current_time)
    later = current_time
    with factory.begin() as db:
        if expiry == "lease":
            later += timedelta(seconds=16)
        elif expiry == "deadline":
            later += timedelta(seconds=61)
        elif expiry == "actor":
            db.get(User, scope.actor_id).is_active = False
        elif expiry == "role":
            db.get(User, scope.actor_id).role = "admin"
        elif expiry == "session":
            db.execute(delete(AuthSession).where(AuthSession.token_hash == scope.session_hash))
        elif expiry == "generation":
            db.get(Conversation, scope.conversation_id).generation_token = uuid4()
        elif expiry == "deleted":
            db.get(Conversation, scope.conversation_id).deleted_at = current_time
        elif expiry == "mode":
            db.get(Conversation, scope.conversation_id).mode = "human"
        else:
            db.get(ComputeWorker, worker.id).is_active = False
    with factory() as db:
        with pytest.raises(AuthError):
            service.submit_result(db, worker, job_id, claim["lease_token"], result(), now=later)
        db.rollback()
    with factory.begin() as db:
        service.cleanup(db, now=later)
        job = db.get(ComputeJob, job_id)
        assert job.status in {"failed", "cancelled"}
        assert job.payload is None and job.result is None
        assert (
            service.claim(
                db,
                service.register_worker(db, name="other", model_id="test-model", now=later)[0],
                now=later,
            )
            is None
        )


@pytest.mark.parametrize("reason", ["cancel", "deadline", "generation", "recover"])
def test_orphan_success_cleanup(factory, current_time, setup_job, reason):
    from app.modules.compute import service
    from app.modules.compute.models import ComputeJob

    scope, worker, _, job_id = setup_job
    with factory.begin() as db:
        claim = service.claim(db, worker, now=current_time)
        service.submit_result(db, worker, job_id, claim["lease_token"], result(), now=current_time)
    with factory.begin() as db:
        if reason == "cancel":
            service.cancel(db, job_id, now=current_time)
            service.cancel(db, job_id, now=current_time)
        elif reason == "generation":
            db.get(Message, scope.assistant_message_id).status = "cancelled"
        service.cleanup(
            db,
            now=current_time + timedelta(seconds=61 if reason == "deadline" else 0),
            recover=reason == "recover",
        )
        job = db.get(ComputeJob, job_id)
        assert job.payload is None and job.result is None
        with pytest.raises(AuthError):
            service.take_result(db, job_id, scope, now=current_time)


def test_heartbeat_cannot_extend_deadline_and_failure_has_safe_code(
    factory, current_time, setup_job
):
    from app.modules.compute import service
    from app.modules.compute.models import ComputeJob

    scope, worker, _, job_id = setup_job
    with factory.begin() as db:
        claim = service.claim(db, worker, now=current_time)
        service.heartbeat(
            db, worker, job_id, claim["lease_token"], now=current_time + timedelta(seconds=10)
        )
        assert db.get(ComputeJob, job_id).deadline == scope.deadline
        service.submit_result(
            db,
            worker,
            job_id,
            claim["lease_token"],
            {"error_code": "PROVIDER_TIMEOUT"},
            now=current_time + timedelta(seconds=20),
        )
        with pytest.raises(AuthError) as exc:
            service.take_result(db, job_id, scope, now=current_time + timedelta(seconds=20))
        assert exc.value.code == "PROVIDER_TIMEOUT"
        assert db.get(ComputeJob, job_id).payload is None


def test_scope_mismatch_and_model_filter(factory, current_time, setup_job):
    from dataclasses import replace

    from app.modules.compute import service

    scope, _, _, job_id = setup_job
    with factory.begin() as db:
        other, _ = service.register_worker(db, name="other", model_id="different", now=current_time)
        assert service.claim(db, other, now=current_time) is None
        with pytest.raises(AuthError):
            service.take_result(db, job_id, replace(scope, actor_id=uuid4()), now=current_time)
        assert service.take_result(db, job_id, scope, now=current_time) is None


def test_retention_and_bound_results(factory, current_time, setup_job):
    from app.modules.compute import service
    from app.modules.compute.models import ComputeJob

    _, worker, _, job_id = setup_job
    with factory.begin() as db:
        claim = service.claim(db, worker, now=current_time)
        for invalid in [
            result("x" * 8193),
            {**result(), "unknown": "secret"},
            {**result(), "finish_reason": None},
            {"error_code": "secret"},
            {**result(), "usage": {"prompt_tokens": True}},
        ]:
            with pytest.raises(AuthError) as exc:
                service.submit_result(
                    db, worker, job_id, claim["lease_token"], invalid, now=current_time
                )
            assert exc.value.status == 422
    with factory.begin() as db:
        service.cleanup(db, now=current_time + timedelta(hours=25))
        assert db.get(ComputeJob, job_id) is None


def test_scope_context_is_reset():
    from app.modules.compute.context import bind_scope, generation_scope

    assert generation_scope.get() is None
    with pytest.raises(RuntimeError), bind_scope("test-scope"):
        assert generation_scope.get() == "test-scope"
        raise RuntimeError("test")
    assert generation_scope.get() is None


@pytest.mark.parametrize("reason", ["deadline", "session", "generation"])
def test_identical_duplicate_cannot_acknowledge_revoked_generation(
    factory, current_time, setup_job, reason
):
    from app.modules.compute import service

    scope, worker, _, job_id = setup_job
    with factory.begin() as db:
        claim = service.claim(db, worker, now=current_time)
        service.submit_result(db, worker, job_id, claim["lease_token"], result(), now=current_time)
    later = current_time
    with factory.begin() as db:
        if reason == "deadline":
            later += timedelta(seconds=61)
        elif reason == "session":
            db.execute(delete(AuthSession).where(AuthSession.token_hash == scope.session_hash))
        else:
            db.get(Message, scope.assistant_message_id).status = "cancelled"
    with factory() as db, pytest.raises(AuthError) as exc:
        service.submit_result(db, worker, job_id, claim["lease_token"], result(), now=later)
    assert exc.value.status == 409


def test_racing_consumers_deliver_once_and_cleanup_preserves_valid_success(
    factory, current_time, setup_job
):
    from app.modules.compute import service

    scope, worker, _, job_id = setup_job
    with factory.begin() as db:
        claim = service.claim(db, worker, now=current_time)
        service.submit_result(db, worker, job_id, claim["lease_token"], result(), now=current_time)

    def consume():
        try:
            with factory.begin() as db:
                service.cleanup(db, now=current_time)
                return service.take_result(db, job_id, scope, now=current_time)
        except AuthError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        consumed = list(pool.map(lambda _: consume(), range(2)))
    assert len([value for value in consumed if value == result()]) == 1
    assert consumed.count(409) == 1


def test_cancel_commit_fences_blocked_submission(factory, current_time, setup_job):
    from threading import Event

    from app.modules.compute import service
    from app.modules.compute.models import ComputeJob

    _, worker, _, job_id = setup_job
    with factory.begin() as db:
        claim = service.claim(db, worker, now=current_time)
    started = Event()

    def submit():
        started.set()
        try:
            with factory.begin() as db:
                service.submit_result(
                    db, worker, job_id, claim["lease_token"], result(), now=current_time
                )
            return "accepted"
        except AuthError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=1) as pool:
        with factory.begin() as db:
            service.cancel(db, job_id, now=current_time)
            future = pool.submit(submit)
            assert started.wait(timeout=5)
        assert future.result(timeout=5) == 409
    with factory() as db:
        job = db.get(ComputeJob, job_id)
        assert job.status == "cancelled" and job.result is None


def test_payload_validation_is_strict_and_byte_bounded(factory, current_time, setup_job):
    from app.modules.compute import service

    scope, _, _, _ = setup_job
    with factory() as db:
        for invalid in [
            {**payload(), "max_tokens": 513},
            {**payload(), "max_tokens": True},
            {**payload(), "temperature": float("nan")},
            {**payload(), "messages": [{"role": "tool", "content": "secret"}]},
            {**payload(), "messages": [{"role": "user", "content": "文" * 4001}]},
        ]:
            with pytest.raises(AuthError) as exc:
                service.enqueue(db, scope, invalid, now=current_time)
            assert exc.value.status == 422


def test_metadata_capacity_never_exceeds_ten_thousand(factory, current_time, setup_job):
    from sqlalchemy import func, insert

    from app.modules.compute import service
    from app.modules.compute.models import ComputeJob

    scope, _, _, _ = setup_job
    with factory.begin() as db:
        data = {key: getattr(scope, key) for key in scope.__dataclass_fields__}
        db.execute(
            insert(ComputeJob),
            [
                dict(
                    data,
                    id=uuid4(),
                    model_id="test-model",
                    status="consumed",
                    created_at=current_time,
                    finished_at=current_time,
                )
                for _ in range(9999)
            ],
        )
    with factory() as db:
        with pytest.raises(AuthError) as exc:
            service.enqueue(db, scope, payload(), now=current_time)
        assert exc.value.status == 429
        assert db.scalar(select(func.count()).select_from(ComputeJob)) == 10000


def test_cleanup_refreshes_existing_session_before_expiring_a_lease(
    factory, current_time, setup_job
):
    from app.modules.compute import service
    from app.modules.compute.models import ComputeJob

    _, worker, _, job_id = setup_job
    with factory.begin() as db:
        claim = service.claim(db, worker, now=current_time)
    with factory() as stale:
        old = stale.get(ComputeJob, job_id)
        assert old.status == "running"
        stale.commit()
        with factory.begin() as db:
            service.submit_result(
                db, worker, job_id, claim["lease_token"], result(), now=current_time
            )
        service.cleanup(stale, now=current_time + timedelta(seconds=16))
        stale.commit()
    with factory() as db:
        job = db.get(ComputeJob, job_id)
        assert job.status == "succeeded"
        assert job.result == result()


def test_downgrade_rejects_big_latency_without_truncating_data(
    factory, migrated_engine, current_time
):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy.exc import DataError

    with factory.begin() as db:
        scope = new_scope(db, current_time)
        db.get(Message, scope.assistant_message_id).latency_ms = 2592000000
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with migrated_engine.begin() as connection:
        config.attributes["connection"] = connection
        with pytest.raises(DataError), connection.begin_nested():
            command.downgrade(config, "012")
    with factory() as db:
        assert db.get(Message, scope.assistant_message_id).latency_ms == 2592000000


@pytest.mark.parametrize("lock_kind", ["advisory", "message", "worker"])
@pytest.mark.parametrize(
    "operation", ["take_deadline", "take_session", "cleanup_lease", "cleanup_deadline"]
)
def test_provider_consumption_and_cleanup_use_post_lock_time(
    factory, current_time, setup_job, monkeypatch, lock_kind, operation
):
    from queue import Queue
    from threading import Event
    from time import monotonic
    from types import SimpleNamespace

    from sqlalchemy import text

    from app.modules.compute import service
    from app.modules.compute.models import ComputeJob, ComputeWorker
    from app.modules.providers import queued

    scope, worker, _, job_id = setup_job
    with factory.begin() as db:
        claim = service.claim(db, worker, now=current_time)
        if operation != "cleanup_lease":
            service.submit_result(
                db, worker, job_id, claim["lease_token"], result(), now=current_time
            )
        if operation == "take_session":
            session = db.scalar(
                select(AuthSession).where(AuthSession.token_hash == scope.session_hash)
            )
            session.expires_at = current_time + timedelta(seconds=10)
    before, after = {"take_session": (9, 11), "cleanup_lease": (14, 16)}.get(operation, (59, 61))
    clock = [current_time + timedelta(seconds=before)]
    monkeypatch.setattr(queued, "datetime", SimpleNamespace(now=lambda timezone: clock[0]))
    pids = Queue()

    def tracked_factory():
        db = factory()
        pids.put(db.scalar(text("SELECT pg_backend_pid()")))
        return db

    provider = queued.QueuedProvider(tracked_factory, model_id="test-model", max_output_tokens=512)

    def invoke():
        try:
            if operation.startswith("take"):
                return provider._transaction(service.take_result, job_id, scope)
            with tracked_factory() as db:
                service.cleanup(db, now=lambda: clock[0])
                db.commit()
        except AuthError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=1) as pool:
        with factory.begin() as blocker:
            if lock_kind == "advisory":
                blocker.execute(text("SELECT pg_advisory_xact_lock(2021, 1)"))
            else:
                model, identity = (
                    (Message, scope.assistant_message_id)
                    if lock_kind == "message"
                    else (ComputeWorker, worker.id)
                )
                blocker.scalar(select(model).where(model.id == identity).with_for_update())
            pending = pool.submit(invoke)
            pid = pids.get(timeout=5)
            waiting, limit = False, monotonic() + 5
            with factory() as observer:
                while monotonic() < limit:
                    waiting = (
                        observer.scalar(
                            text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pid}
                        )
                        > 0
                    )
                    if waiting:
                        break
                    Event().wait(0.01)
            assert waiting, "The operation must actually be blocked by PostgreSQL"
            clock[0] = current_time + timedelta(seconds=after)
        outcome = pending.result(timeout=5)
    if operation.startswith("take"):
        assert outcome == 409
    else:
        with factory() as db:
            job = db.get(ComputeJob, job_id)
            assert job.status in {"failed", "cancelled"}
            assert job.payload is None and job.result is None
