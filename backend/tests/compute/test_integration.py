import asyncio
from datetime import UTC, datetime, timedelta
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.security import token_hash
from app.modules.auth.models import AuthSession
from app.modules.chat.streaming import GenerationStream
from tests.chat.chat_stream_helpers import reply
from tests.chat.data_helpers import ChatData
from tests.chat.test_app_startup import settings_for
from tests.conftest import migrated_engine as migrate_test_schema


@pytest.fixture
def migrated_engine(database_url):
    # Queue operations commit on independent connections, so each test needs its own schema.
    yield from migrate_test_schema.__wrapped__(database_url)


@pytest.fixture
def compute_api():
    try:
        return tuple(
            import_module("app.modules.compute." + name)
            for name in ("context", "service", "models")
        )
    except ModuleNotFoundError:
        pytest.fail("compute integration implementation is missing", pytrace=False)


def generation(factory, *, rag, now, data=None, kb_ids=None):
    data = data or ChatData(factory)
    reservation = data.reserve(data.conversation(kb_ids=kb_ids), now=now)
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
        db.commit()
    state = SimpleNamespace(
        session_factory=factory, chat_rag=rag, chat_clock=lambda: now, auth_clock=lambda: now
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state), cookies={"qa_session": raw_session})
    return GenerationStream(request, reservation), raw_session


def test_parallel_streams_bind_server_identity_and_reset_context(migrated_engine, compute_api):
    context = compute_api[0]
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    observed = []

    class OverlappingRAG:
        async def stream_answer(self, actor, kb_ids, question, history):
            scope = context.generation_scope.get()
            observed.append(scope)
            while len(observed) < 2:
                await asyncio.sleep(0)
            assert context.generation_scope.get() is scope
            for event in reply():
                yield event

    now = datetime.now(UTC)
    streams = [generation(factory, rag=OverlappingRAG(), now=now) for _ in range(2)]

    async def consume(stream):
        result = [event async for event in stream.events()]
        assert context.generation_scope.get() is None
        assert any("event: done" in event for event in result)

    async def run():
        await asyncio.gather(*(consume(stream) for stream, _ in streams))

    asyncio.run(run())
    assert len({scope.conversation_id for scope in observed}) == 2
    for stream, raw_session in streams:
        scope = next(
            item for item in observed if item.conversation_id == stream.reservation.conversation_id
        )
        assert scope.conversation_id == stream.reservation.conversation_id
        assert scope.assistant_message_id == stream.reservation.assistant_message_id
        assert scope.generation_token == stream.reservation.token
        assert scope.actor_id == stream.reservation.actor.user_id
        assert scope.actor_role == "user"
        assert scope.session_hash == token_hash(raw_session)
        assert scope.deadline == now + timedelta(seconds=60)


def test_early_iterator_close_restores_previous_scope(migrated_engine, compute_api):
    context = compute_api[0]
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    stream, _ = generation(factory, rag=None, now=datetime.now(UTC))

    async def run():
        iterator = stream.events()
        await anext(iterator)  # meta precedes RAG
        assert context.generation_scope.get() is not None
        await iterator.aclose()
        assert context.generation_scope.get() is None
        await stream.close()

    asyncio.run(run())


def test_machine_routes_bearer_body_limit_and_normal_csrf(migrated_engine, tmp_path, compute_api):
    from app.main import create_app

    app = create_app(settings_for(migrated_engine, tmp_path))
    with TestClient(app) as client:
        missing = client.post("/internal/compute/claim", json={})
        assert missing.status_code == 401
        assert missing.headers["cache-control"] == "no-store"
        oversized = client.post("/internal/compute/claim", content=iter([b" " * 40000] * 2))
        assert oversized.status_code == 413
        assert oversized.headers["cache-control"] == "no-store"
        browser = client.post("/api/v1/conversations", json={})
        assert browser.status_code == 403
        assert browser.json()["error"]["code"] == "CSRF_FAILED"


def test_startup_recovers_chat_then_invalidates_old_compute(migrated_engine, tmp_path, compute_api):
    from app.main import create_app

    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    stream, raw_session = generation(factory, rag=None, now=datetime.now(UTC))
    r = stream.reservation
    scope = compute_api[0].GenerationScope(
        conversation_id=r.conversation_id,
        assistant_message_id=r.assistant_message_id,
        generation_token=r.token,
        actor_id=r.actor.user_id,
        actor_role=r.actor.role,
        session_hash=token_hash(raw_session),
        deadline=r.accepted_at + timedelta(seconds=60),
    )
    with factory() as db:
        job_id = compute_api[1].enqueue(
            db,
            scope,
            {
                "model_id": "local-model",
                "messages": [{"role": "user", "content": "private"}],
                "max_tokens": 64,
                "temperature": 0,
            },
            now=datetime.now(UTC),
        )
        db.commit()
    app = create_app(settings_for(migrated_engine, tmp_path))
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 200
        with factory() as db:
            row = db.get(compute_api[2].ComputeJob, job_id)
            assert row.status in {"failed", "cancelled"}
            assert row.payload is None and row.result is None


def test_failed_compute_recovery_blocks_readiness_without_private_errors(
    migrated_engine, tmp_path, monkeypatch, compute_api, caplog
):
    from sqlalchemy.exc import OperationalError

    import app.main as main

    def fail(*args, **kwargs):
        raise OperationalError("private-compute-query", {}, Exception("private-compute-body"))

    monkeypatch.setattr(compute_api[1], "cleanup", fail)
    app = main.create_app(settings_for(migrated_engine, tmp_path))
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/health/ready")
        assert response.status_code == 503
    assert "private-compute" not in caplog.text + response.text


def test_periodic_cleanup_retries_after_database_failure_and_stops_on_shutdown(
    migrated_engine, tmp_path, monkeypatch, compute_api, caplog
):
    import threading

    from sqlalchemy.exc import OperationalError

    import app.main as main

    original_cleanup = compute_api[1].cleanup
    original_sleep = asyncio.sleep
    periodic, recovered = [], threading.Event()

    async def tick(delay):
        await original_sleep(0.01 if delay == 60 else delay)

    def cleanup(db, *, now, recover=False):
        if not recover:
            periodic.append(now)
            if len(periodic) == 1:
                raise OperationalError("private-periodic-query", {}, Exception("private-periodic"))
            recovered.set()
        return original_cleanup(db, now=now, recover=recover)

    monkeypatch.setattr(main.asyncio, "sleep", tick)
    monkeypatch.setattr(compute_api[1], "cleanup", cleanup)
    app = main.create_app(settings_for(migrated_engine, tmp_path))
    with TestClient(app) as client:
        assert recovered.wait(3)
        assert client.get("/health/ready").status_code == 200
    count = len(periodic)
    threading.Event().wait(0.05)
    assert len(periodic) == count
    assert "COMPUTE_CLEANUP_FAILED" in caplog.text
    assert "private-periodic" not in caplog.text


def test_recover_generation_after_thirty_days_preserves_full_latency(migrated_engine):
    from app.modules.chat.models import Message
    from app.modules.chat.service import recover_generations

    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    data = ChatData(factory)
    now = datetime.now(UTC)
    reservation = data.reserve(data.conversation(), now=now - timedelta(days=30))
    recover_generations(factory, now)
    with factory() as db:
        row = db.get(Message, reservation.assistant_message_id)
        assert row.status == "failed"
        assert row.latency_ms == 2592000000


@pytest.mark.parametrize("mode", ["valid", "invented_quote", "source_changed", "length"])
def test_queued_result_passes_real_rag_citation_and_source_revalidation(
    migrated_engine, compute_api, mode
):
    import json

    from app.modules.chat.models import Message
    from app.modules.ingestion.models import Document
    from app.modules.providers.queued import QueuedProvider
    from app.modules.rag.service import RAGService
    from app.modules.retrieval.service import RetrievalService
    from tests.retrieval.search_helpers import FixedEmbedder

    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    data = ChatData(factory)
    kb = data.kb(visibility="public")
    quote = "图书馆每天上午九点开放。"
    document_id, _, _ = data.document(kb, text=quote)
    retrieval = RetrievalService(factory, FixedEmbedder())
    rag = RAGService(
        retrieval.search,
        retrieval.validate_hits,
        QueuedProvider(factory, model_id="local-model", max_output_tokens=512),
    )
    now = datetime.now(UTC)
    stream, _ = generation(factory, rag=rag, now=now, data=data, kb_ids=[kb])
    with factory() as db:
        worker, _ = compute_api[1].register_worker(
            db, name=uuid4().hex, model_id="local-model", now=now
        )
        db.commit()

    async def run():
        async def consume():
            return [event async for event in stream.events()]

        pending = asyncio.create_task(consume())
        for _ in range(300):
            with factory() as db:
                claimed = compute_api[1].claim(db, worker, now=datetime.now(UTC))
                db.commit()
            if claimed:
                break
            await asyncio.sleep(0.01)
        assert claimed is not None
        assert not pending.done()
        selected = "invented-private-output" if mode == "invented_quote" else quote
        with factory() as db:
            if mode == "source_changed":
                db.get(Document, document_id).status = "disabled"
            compute_api[1].submit_result(
                db,
                worker,
                claimed["job_id"],
                claimed["lease_token"],
                {
                    "model_id": "local-model",
                    "text": json.dumps(
                        {"status": "answered", "selections": [{"index": 1, "quote": selected}]}
                    ),
                    "finish_reason": "length" if mode == "length" else "stop",
                    "usage": None,
                },
                now=datetime.now(UTC),
            )
            db.commit()
        events = await asyncio.wait_for(pending, 3)
        assert compute_api[0].generation_scope.get() is None
        return "".join(events)

    events = asyncio.run(run())
    with factory() as db:
        message = db.get(Message, stream.reservation.assistant_message_id)
        if mode == "valid":
            assert "event: done" in events
            assert quote in events and quote in message.content
            assert message.citations[0]["source_id"] == str(document_id)
        else:
            assert quote not in events + message.content
            assert "invented-private-output" not in events + message.content
            if mode == "source_changed":
                assert "SOURCE_CHANGED" in events
            elif mode == "length":
                assert "PROVIDER_UNSUPPORTED_RESPONSE" in events
            else:
                assert message.answer_status == "no_answer"


def test_shutdown_waits_for_inflight_cleanup_transaction(
    migrated_engine, tmp_path, monkeypatch, compute_api
):
    import threading

    import app.main as main

    original_cleanup, original_sleep = compute_api[1].cleanup, asyncio.sleep
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()

    async def tick(delay):
        await original_sleep(0.01 if delay == 60 else delay)

    def cleanup(db, *, now, recover=False):
        if not recover:
            entered.set()
            assert release.wait(3)
        result = original_cleanup(db, now=now, recover=recover)
        if not recover:
            completed.set()
        return result

    def delayed_release():
        threading.Event().wait(0.2)
        release.set()

    monkeypatch.setattr(main.asyncio, "sleep", tick)
    monkeypatch.setattr(compute_api[1], "cleanup", cleanup)
    app = main.create_app(settings_for(migrated_engine, tmp_path))
    with TestClient(app):
        assert entered.wait(3)
        releaser = threading.Thread(target=delayed_release)
        releaser.start()
    complete_at_shutdown = completed.is_set()
    releaser.join()
    assert completed.wait(3)
    assert complete_at_shutdown
