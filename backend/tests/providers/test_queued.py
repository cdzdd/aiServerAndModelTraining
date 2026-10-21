import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.security import token_hash
from app.modules.auth.models import AuthSession
from app.modules.providers.config import ModelSettings
from app.modules.providers.errors import ProviderError
from app.modules.providers.factory import create_provider
from app.modules.providers.schemas import LLMMessage
from tests.chat.data_helpers import ChatData
from tests.conftest import migrated_engine as migrate_test_schema

MESSAGES = [LLMMessage(role="user", content="开放时间？")]


def queued_settings(**overrides):
    values = dict(
        model_provider="queued",
        model_id="local-model",
        model_allowed_ids=["local-model"],
        model_base_url="",
        model_api_key="",
    )
    values.update(overrides)
    return ModelSettings(_env_file=None, **values)


def test_queued_selection_requires_explicit_database_and_allowlisted_model():
    config = queued_settings()
    with pytest.raises(ProviderError) as error:
        create_provider(config)
    assert error.value.code == "PROVIDER_CONFIG_ERROR"
    provider = create_provider(config, session_factory=sessionmaker())
    assert type(provider).__name__ == "QueuedProvider"
    for overrides in ({"model_id": "unknown"}, {"model_allowed_ids": []}):
        with pytest.raises(ValidationError):
            queued_settings(**overrides)


@pytest.fixture
def migrated_engine(database_url):
    # Queue operations commit on independent connections, so each test needs its own schema.
    yield from migrate_test_schema.__wrapped__(database_url)


@pytest.fixture
def api():
    try:
        return tuple(
            import_module("app.modules." + name)
            for name in ("providers.queued", "compute.context", "compute.service", "compute.models")
        )
    except ModuleNotFoundError:
        pytest.fail("queued provider implementation is missing", pytrace=False)


@pytest.fixture
def queue_data(migrated_engine, api):
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    data = ChatData(factory)
    now = datetime.now(UTC)
    reservation = data.reserve(data.conversation(), now=now)
    raw_session = uuid4().hex
    with factory() as db:
        db.add(
            AuthSession(
                user_id=data.actor.user_id,
                token_hash=token_hash(raw_session),
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        worker, _ = api[2].register_worker(db, name=uuid4().hex, model_id="local-model", now=now)
        db.commit()
    scope = api[1].GenerationScope(
        conversation_id=reservation.conversation_id,
        assistant_message_id=reservation.assistant_message_id,
        generation_token=reservation.token,
        actor_id=data.actor.user_id,
        actor_role=data.actor.role,
        session_hash=token_hash(raw_session),
        deadline=now + timedelta(seconds=60),
    )
    return factory, scope, worker


def provider(api, factory):
    return api[0].QueuedProvider(factory, model_id="local-model", max_output_tokens=512)


def test_queued_requires_bound_scope_without_enqueuing(api, migrated_engine):
    async def run():
        with pytest.raises(ProviderError) as error:
            await anext(
                provider(api, sessionmaker(bind=migrated_engine)).stream(
                    MESSAGES, max_tokens=64, temperature=0
                )
            )
        assert error.value.code == "PROVIDER_CONFIG_ERROR"

    asyncio.run(run())


@pytest.mark.parametrize("finish_reason", ["stop", "length"])
def test_queued_waits_consumes_once_and_preserves_terminal_usage(api, queue_data, finish_reason):
    factory, scope, worker = queue_data

    async def run():
        with api[1].bind_scope(scope):
            stream = provider(api, factory).stream(MESSAGES, max_tokens=64, temperature=0)
            pending = asyncio.create_task(anext(stream))
            for _ in range(200):
                with factory() as db:
                    claimed = api[2].claim(db, worker, now=datetime.now(UTC))
                    db.commit()
                if claimed:
                    break
                await asyncio.sleep(0.01)
            assert claimed is not None
            assert not pending.done()
            assert claimed["payload"]["messages"] == [{"role": "user", "content": "开放时间？"}]
            with factory() as db:
                api[2].submit_result(
                    db,
                    worker,
                    claimed["job_id"],
                    claimed["lease_token"],
                    {
                        "model_id": "local-model",
                        "text": "九点开放。",
                        "finish_reason": finish_reason,
                        "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
                    },
                    now=datetime.now(UTC),
                )
                db.commit()
            delta = await asyncio.wait_for(pending, 3)
            assert delta.text == "九点开放。"
            assert delta.finish_reason == finish_reason
            assert delta.usage.total_tokens == 16
            await stream.aclose()
            with factory() as db:
                row = db.get(api[3].ComputeJob, claimed["job_id"])
                assert row.payload is None and row.result is None
        assert api[1].generation_scope.get() is None

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["cancel", "timeout", "failure"])
def test_queued_cancellation_timeout_and_failure_clear_private_bodies(api, queue_data, mode):
    factory, scope, worker = queue_data
    if mode == "timeout":
        scope = replace(scope, deadline=datetime.now(UTC) + timedelta(seconds=0.3))

    async def run():
        with api[1].bind_scope(scope):
            stream = provider(api, factory).stream(MESSAGES, max_tokens=64, temperature=0)
            pending = asyncio.create_task(anext(stream))
            for _ in range(200):
                with factory() as db:
                    job = db.scalar(
                        select(api[3].ComputeJob).where(
                            api[3].ComputeJob.assistant_message_id == scope.assistant_message_id
                        )
                    )
                if job:
                    break
                await asyncio.sleep(0.01)
            assert job is not None
            if mode == "cancel":
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                with factory() as db:
                    if mode == "failure":
                        claimed = api[2].claim(db, worker, now=datetime.now(UTC))
                        api[2].submit_result(
                            db,
                            worker,
                            claimed["job_id"],
                            claimed["lease_token"],
                            {"error_code": "PROVIDER_AUTH_FAILED"},
                            now=datetime.now(UTC),
                        )
                    db.commit()
                with pytest.raises(ProviderError) as error:
                    await asyncio.wait_for(pending, 3)
                expected = "PROVIDER_TIMEOUT" if mode == "timeout" else "PROVIDER_AUTH_FAILED"
                assert error.value.code == expected
            await stream.aclose()
            with factory() as db:
                row = db.get(api[3].ComputeJob, job.id)
                assert row.status in {"cancelled", "failed"}
                assert row.payload is None and row.result is None

    asyncio.run(run())


def test_cancellation_during_enqueue_waits_for_job_id_then_clears_body(
    api, queue_data, monkeypatch
):
    import threading

    factory, scope, _ = queue_data
    entered, release = threading.Event(), threading.Event()
    original = api[2].enqueue

    def paused_enqueue(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(api[2], "enqueue", paused_enqueue)

    async def run():
        with api[1].bind_scope(scope):
            iterator = provider(api, factory).stream(MESSAGES, max_tokens=64, temperature=0)
            pending = asyncio.create_task(anext(iterator))
            assert await asyncio.to_thread(entered.wait, 3)
            pending.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await pending
            await iterator.aclose()
        with factory() as db:
            row = db.scalar(
                select(api[3].ComputeJob).where(
                    api[3].ComputeJob.assistant_message_id == scope.assistant_message_id
                )
            )
            assert row is not None and row.status == "cancelled"
            assert row.payload is None and row.result is None

    asyncio.run(run())


def test_deadline_crossing_inside_result_transaction_reports_timeout(api, queue_data, monkeypatch):
    import time

    factory, scope, _ = queue_data
    scope = replace(scope, deadline=datetime.now(UTC) + timedelta(seconds=0.15))
    original = api[2].take_result

    def delayed_result(*args, **kwargs):
        time.sleep(0.2)
        kwargs["now"] = datetime.now(UTC)
        return original(*args, **kwargs)

    monkeypatch.setattr(api[2], "take_result", delayed_result)

    async def run():
        with api[1].bind_scope(scope):
            with pytest.raises(ProviderError) as error:
                await anext(provider(api, factory).stream(MESSAGES, max_tokens=64, temperature=0))
            assert error.value.code == "PROVIDER_TIMEOUT"

    asyncio.run(run())


def test_anyio_cancellation_during_enqueue_cannot_orphan_job(api, queue_data, monkeypatch):
    import threading

    import anyio

    factory, scope, _ = queue_data
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    original = api[2].enqueue

    def paused_enqueue(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        result = original(*args, **kwargs)
        completed.set()
        return result

    monkeypatch.setattr(api[2], "enqueue", paused_enqueue)

    async def run():
        async with anyio.create_task_group() as group:

            async def consume():
                with api[1].bind_scope(scope):
                    iterator = provider(api, factory).stream(MESSAGES, max_tokens=64, temperature=0)
                    try:
                        await anext(iterator)
                    finally:
                        await iterator.aclose()

            group.start_soon(consume)
            assert await asyncio.to_thread(entered.wait, 3)
            group.cancel_scope.cancel()
            release.set()
        assert await asyncio.to_thread(completed.wait, 3)
        # Wait for the real enqueue transaction's commit, not only its service return.
        for _ in range(100):
            with factory() as db:
                row = db.scalar(
                    select(api[3].ComputeJob).where(
                        api[3].ComputeJob.assistant_message_id == scope.assistant_message_id
                    )
                )
            if row:
                break
            await asyncio.sleep(0.01)
        assert row is not None and row.status == "cancelled"
        assert row.payload is None and row.result is None

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["enqueue", "cancel"])
def test_repeated_native_cancel_waits_for_enqueue_and_terminal_commit(
    api, queue_data, monkeypatch, phase
):
    import threading

    factory, scope, _ = queue_data
    entered, release, committed = threading.Event(), threading.Event(), threading.Event()
    operation = getattr(api[2], phase)
    instance = provider(api, factory)
    transaction = instance._transaction

    def paused_operation(*args, **kwargs):
        result = operation(*args, **kwargs)
        # Real INSERT/body clearing has flushed; its own transaction has not committed yet.
        entered.set()
        assert release.wait(3)
        return result

    monkeypatch.setattr(api[2], phase, paused_operation)

    def observed_transaction(action, *args):
        result = transaction(action, *args)
        if action is paused_operation:
            committed.set()
        return result

    monkeypatch.setattr(instance, "_transaction", observed_transaction)

    async def run():
        with api[1].bind_scope(scope):
            iterator = instance.stream(MESSAGES, max_tokens=64, temperature=0)
            pending = asyncio.create_task(anext(iterator))
            if phase == "cancel":
                for _ in range(100):
                    with factory() as db:
                        queued = db.scalar(
                            select(api[3].ComputeJob).where(
                                api[3].ComputeJob.assistant_message_id == scope.assistant_message_id
                            )
                        )
                    if queued:
                        break
                    await asyncio.sleep(0.01)
                assert queued is not None
                pending.cancel()
            assert await asyncio.to_thread(entered.wait, 3)
            pending.cancel()
            await asyncio.sleep(0)
            pending.cancel()
            await asyncio.sleep(0)
            ended_before_commit = pending.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert await asyncio.to_thread(committed.wait, 3)
            await iterator.aclose()
        with factory() as db:
            row = db.scalar(
                select(api[3].ComputeJob).where(
                    api[3].ComputeJob.assistant_message_id == scope.assistant_message_id
                )
            )
            assert row is not None and row.status == "cancelled"
            assert row.payload is None and row.result is None
        assert not ended_before_commit

    asyncio.run(run())
