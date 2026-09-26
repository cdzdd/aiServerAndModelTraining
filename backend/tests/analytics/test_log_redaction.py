"""Log privacy and correlation are checked against rendered application records."""

import asyncio
import json
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.audit import _redact
from app.modules.chat.streaming import GenerationStream
from app.modules.providers.errors import ProviderError
from app.modules.rag.service import RAGService
from tests.rag.service_helpers import ACTOR, KB_IDS, ScriptedProvider, Sources, hit

SECRET = "PRIVATE_SENTINEL_never_log"


def records(caplog, event):
    result = []
    for record in caplog.records:
        if record.name.startswith("app."):
            value = json.loads(record.getMessage())
            if value.get("event") == event:
                result.append(value)
    assert SECRET not in caplog.text
    return result


def test_audit_comment_resolution_nested_defense():
    assert _redact({"Comment": SECRET, "nested": [{"Resolution": SECRET, "count": 2}]}) == {
        "Comment": "[REDACTED]",
        "nested": [{"Resolution": "[REDACTED]", "count": 2}],
    }


def test_provider_error_without_http_has_null_request_and_no_payload(caplog):
    sources = Sources([hit(SECRET)])
    error = ProviderError("PROVIDER_AUTH_FAILED")
    error.args = (SECRET,)
    provider = ScriptedProvider([error])

    async def run():
        return [
            item
            async for item in RAGService(sources.search, sources.validate, provider).stream_answer(
                ACTOR, KB_IDS, "图书馆开放时间？" + SECRET, []
            )
        ]

    result = asyncio.run(run())
    assert result[0].payload["code"] == "PROVIDER_AUTH_FAILED"
    logged = records(caplog, "rag_failure")
    assert len(logged) == 1
    assert logged[0]["error_code"] == "PROVIDER_AUTH_FAILED"
    assert logged[0]["request_id"] is None
    assert set(logged[0]) == {"event", "error_code", "request_id", "prompt_version"}
    assert provider.closed == 1


@pytest.mark.parametrize(
    "path,event,code",
    [
        ("events", "chat_finalization_failed", "CHAT_FINALIZATION_FAILED"),
        ("close", "chat_cancellation_persistence_failed", "CHAT_CANCELLATION_PERSISTENCE_FAILED"),
    ],
)
def test_stream_persistence_failure_uses_reservation_id(caplog, path, event, code):
    request_id = str(uuid4())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    generation = GenerationStream(request, SimpleNamespace(request_id=request_id))

    def fail(*args, **kwargs):
        raise RuntimeError(SECRET)

    generation._current = fail
    generation._finish = fail

    async def run():
        if path == "events":
            emitted = [item async for item in generation.events()]
            assert "GENERATION_FAILED" in emitted[0]
        else:
            await generation.close()

    asyncio.run(run())
    assert records(caplog, event) == [
        {"event": event, "error_code": code, "request_id": request_id}
    ]


@pytest.fixture
def log_app(migrated_engine, tmp_path):
    from app.main import create_app
    from tests.chat.test_app_startup import settings_for

    app = create_app(settings_for(migrated_engine, tmp_path))
    yield app
    app.state.engine.dispose()


def test_http_auth_failure_and_uncaught_exception_emit_only_safe_fields(log_app, caplog):
    from fastapi.testclient import TestClient

    from tests.auth.conftest import csrf

    @log_app.get("/log-test-error")
    def explode():
        raise RuntimeError(SECRET)

    caplog.set_level(logging.INFO, logger="app.requests")
    with TestClient(log_app) as client:
        client.cookies.set("unused", SECRET)
        request_id = str(uuid4())
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "missing-user", "password": SECRET},
            headers={
                **csrf(client),
                "Authorization": "Bearer " + SECRET,
                "X-Request-ID": request_id,
            },
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
        failure = next(
            item for item in records(caplog, "http_request") if item["request_id"] == request_id
        )
        assert failure["error_code"] == "INVALID_CREDENTIALS"
        assert set(failure) == {
            "event",
            "request_id",
            "method",
            "route",
            "status_code",
            "error_code",
        }
        assert client.get("/log-test-error?private=" + SECRET).status_code == 500
        assert records(caplog, "http_request")[-1]["error_code"] == "INTERNAL_ERROR"
        assert client.get("/" + SECRET, headers={"X-Request-ID": SECRET}).status_code == 404
        last = records(caplog, "http_request")[-1]
        assert last["route"] == "<unmatched>" and last["request_id"] != SECRET


def test_concurrent_http_and_sse_child_tasks_inherit_correct_context(log_app, caplog):
    import httpx2
    from fastapi.responses import StreamingResponse

    from app.core.request_context import request_id_context
    from app.modules.rag.service import _error

    ids = [str(uuid4()), str(uuid4())]
    observed = []

    async def run():
        arrived, count = asyncio.Event(), 0

        @log_app.get("/log-test-stream/{slot}")
        async def stream(slot: int):
            nonlocal count
            count += 1
            if count == 2:
                arrived.set()
            await asyncio.wait_for(arrived.wait(), 3)

            async def body():
                yield b"start\n"
                await asyncio.sleep(0)

                async def child():
                    observed.append((slot, request_id_context.get()))
                    _error("PROVIDER_TIMEOUT" if slot == 0 else "PROVIDER_UNAVAILABLE")

                await asyncio.create_task(child())
                yield b"end\n"

            return StreamingResponse(body(), media_type="text/event-stream")

        assert request_id_context.get() is None
        transport = httpx2.ASGITransport(app=log_app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            responses = await asyncio.gather(
                *[
                    client.get(f"/log-test-stream/{slot}", headers={"X-Request-ID": ids[slot]})
                    for slot in range(2)
                ]
            )
        assert all(item.text == "start\nend\n" for item in responses)
        assert request_id_context.get() is None
        _error("RAG_UNAVAILABLE")

    asyncio.run(run())
    assert sorted(observed) == list(enumerate(ids))
    failures = records(caplog, "rag_failure")
    assert {item["request_id"]: item["error_code"] for item in failures} == {
        ids[0]: "PROVIDER_TIMEOUT",
        ids[1]: "PROVIDER_UNAVAILABLE",
        None: "RAG_UNAVAILABLE",
    }


def test_startup_failure_has_operation_id_and_no_http_context(log_app, monkeypatch, caplog):
    from uuid import UUID

    from fastapi.testclient import TestClient
    from sqlalchemy.exc import OperationalError

    import app.main as main

    def fail(*args):
        raise OperationalError(SECRET, {}, Exception(SECRET))

    monkeypatch.setattr(main, "recover_generations", fail)
    with TestClient(log_app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
    value = records(caplog, "chat_recovery_failed")[0]
    assert value["request_id"] is None and UUID(value["operation_id"])
    assert value["error_code"] == "CHAT_RECOVERY_FAILED"


def make_job(factory, tmp_path, kind):
    from datetime import UTC, datetime, timedelta

    from app.modules.ingestion.models import IngestionJob
    from tests.retrieval.search_helpers import SearchData

    data = SearchData(factory)
    kb = data.kb(visibility="public")
    document_id, revision_id, _ = data.document(kb, text=SECRET)
    with factory() as db:
        job = IngestionJob(
            kind=kind,
            document_id=document_id,
            revision_id=revision_id,
            state="running",
            attempts=2,
            lease_token=uuid4(),
            lease_until=datetime.now(UTC) + timedelta(seconds=60),
        )
        db.add(job)
        db.commit()
        db.expunge(job)
    return job


@pytest.mark.parametrize("kind", ["parse", "index"])
@pytest.mark.parametrize("stale", [False, True])
def test_worker_failure_logs_only_committed_current_lease(
    migrated_engine, tmp_path, caplog, monkeypatch, kind, stale
):
    from sqlalchemy.orm import sessionmaker

    from app.core.request_context import request_id_context
    from app.modules.ingestion import worker
    from app.modules.ingestion.models import IngestionJob
    from app.modules.ingestion.parsers import ParseError
    from app.modules.retrieval import indexing
    from app.modules.retrieval.embedding import EmbeddingError

    factory = sessionmaker(migrated_engine, expire_on_commit=False)
    claimed = make_job(factory, tmp_path, kind)
    token = claimed.lease_token
    expected = "PARSE_FAILED" if kind == "parse" else "ENCODE_FAILED"

    def failure(*args):
        if stale:
            with factory() as db:
                db.get(IngestionJob, claimed.id).lease_token = uuid4()
                db.commit()
        error = ParseError(expected) if kind == "parse" else EmbeddingError(expected)
        error.args = (SECRET,)
        raise error

    monkeypatch.setattr(worker, "bounded_parse", failure)
    settings = SimpleNamespace(upload_dir=tmp_path)
    context_token = request_id_context.set(str(uuid4()))
    try:
        if kind == "parse":
            worker.process_job(factory, settings, claimed)
        else:
            indexing.process_job(
                factory, settings, claimed, embedder=SimpleNamespace(encode_passages=failure)
            )
    finally:
        request_id_context.reset(context_token)
    values = records(caplog, "ingestion_job_failed")
    with factory() as db:
        saved = db.get(IngestionJob, claimed.id)
        if stale:
            assert values == [] and saved.state == "running"
        else:
            assert saved.state == "failed" and saved.lease_token is None
            assert values == [
                {
                    "event": "ingestion_job_failed",
                    "error_code": expected,
                    "request_id": None,
                    "job_id": str(claimed.id),
                    "operation_id": str(token),
                    "kind": kind,
                    "attempt": 2,
                }
            ]


def test_stream_body_close_failure_releases_runtime_with_explicit_id(caplog):
    from app.modules.chat.runtime import ChatRuntime
    from app.modules.chat.streaming import ChatStreamingResponse

    cid, request_id = uuid4(), str(uuid4())
    runtime = ChatRuntime()
    slot = runtime.reserve(cid)
    closed = []

    class BrokenIterator:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def aclose(self):
            raise RuntimeError(SECRET)

    async def close():
        closed.append(True)

    async def run():
        response = ChatStreamingResponse(
            SimpleNamespace(
                reservation=SimpleNamespace(conversation_id=cid, request_id=request_id),
                events=BrokenIterator,
                close=close,
            ),
            runtime,
            slot,
        )

        async def receive():
            await asyncio.Event().wait()

        async def send(message):
            pass

        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        assert runtime.reserve(cid)

    asyncio.run(run())
    assert closed == [True]
    assert records(caplog, "chat_stream_close_failed") == [
        {
            "event": "chat_stream_close_failed",
            "error_code": "CHAT_STREAM_CLOSE_FAILED",
            "request_id": request_id,
        }
    ]


@pytest.mark.parametrize("kind", ["parse", "index"])
def test_worker_commit_failure_does_not_log_a_persisted_outcome(
    migrated_engine, tmp_path, caplog, monkeypatch, kind
):
    from sqlalchemy.orm import Session, sessionmaker

    from app.modules.ingestion import worker
    from app.modules.ingestion.models import IngestionJob
    from app.modules.ingestion.parsers import ParseError
    from app.modules.retrieval import indexing
    from app.modules.retrieval.embedding import EmbeddingError

    factory = sessionmaker(migrated_engine, expire_on_commit=False)
    job = make_job(factory, tmp_path, kind)

    class FailedCommit(Session):
        def commit(self):
            if any(
                isinstance(row, IngestionJob) and row.state == "failed"
                for row in self.identity_map.values()
            ):
                raise RuntimeError(SECRET)
            super().commit()

    failing_factory = sessionmaker(migrated_engine, class_=FailedCommit, expire_on_commit=False)

    def fail(*args):
        raise ParseError("PARSE_FAILED") if kind == "parse" else EmbeddingError("ENCODE_FAILED")

    monkeypatch.setattr(worker, "bounded_parse", fail)
    with pytest.raises(RuntimeError, match=SECRET):
        if kind == "parse":
            worker.process_job(failing_factory, SimpleNamespace(upload_dir=tmp_path), job)
        else:
            indexing.process_job(
                failing_factory,
                SimpleNamespace(),
                job,
                embedder=SimpleNamespace(encode_passages=fail),
            )
    assert records(caplog, "ingestion_job_failed") == []
    with factory() as db:
        assert db.get(IngestionJob, job.id).state == "running"


def test_unknown_codes_and_failed_log_handlers_cannot_leak_or_break_business(caplog):
    from app.core.request_context import log_failure, safe_error_code

    for code in (
        "PROCESS_RESTARTED",
        "AUTHORITY_CHANGED",
        "CANCELLED",
        "INCOMPLETE_STREAM",
        "GENERATION_FAILED",
        "GENERATION_REVOKED",
    ):
        assert safe_error_code(code) == code
    log_failure(
        logging.getLogger("app.log-test"),
        "rag_failure",
        SECRET,
        request_id=SECRET,
        prompt_version=SECRET,
    )
    assert records(caplog, "rag_failure") == [
        {
            "event": "rag_failure",
            "error_code": "UNKNOWN_ERROR",
            "request_id": None,
            "prompt_version": None,
        }
    ]

    class BrokenHandler(logging.Handler):
        def emit(self, record):
            raise RuntimeError(SECRET)

    logger = logging.getLogger("app.broken-test")
    handler = BrokenHandler()
    logger.addHandler(handler)
    try:
        log_failure(logger, "rag_failure", "RAG_UNAVAILABLE")
    finally:
        logger.removeHandler(handler)


def test_actual_malformed_document_logs_format_code_not_file_content(
    migrated_engine, tmp_path, caplog
):
    from sqlalchemy.orm import sessionmaker

    from app.modules.ingestion.models import DocumentRevision
    from app.modules.ingestion.worker import process_job
    from tests.ingestion.test_worker import tokenizer

    factory = sessionmaker(migrated_engine, expire_on_commit=False)
    job = make_job(factory, tmp_path, "parse")
    with factory() as db:
        revision = db.get(DocumentRevision, job.revision_id)
        revision.file_type = "docx"
        (tmp_path / revision.storage_key).write_bytes(SECRET.encode())
        db.commit()
    process_job(factory, SimpleNamespace(upload_dir=tmp_path), job, tokenizer=tokenizer())
    values = records(caplog, "ingestion_job_failed")
    assert values[0]["error_code"] == "INVALID_FORMAT"


def test_configured_stdout_failure_never_prints_exception_context(capsys):
    from app.core.request_context import _SafeStreamHandler, log_failure

    class BrokenOutput:
        def write(self, value):
            raise OSError(SECRET)

        def flush(self):
            pass

    logger = logging.getLogger("app.stdout-failure-test")
    handler = _SafeStreamHandler(BrokenOutput())
    logger.addHandler(handler)
    try:
        try:
            raise RuntimeError(SECRET)
        except RuntimeError:
            log_failure(logger, "rag_failure", "RAG_UNAVAILABLE")
    finally:
        logger.removeHandler(handler)
    assert SECRET not in capsys.readouterr().err


@pytest.mark.parametrize("cancel", [False, True])
def test_http_middleware_restores_existing_context_even_on_cancellation(log_app, cancel):
    from fastapi import Request
    from starlette.responses import Response

    from app.core.request_context import request_id_context

    dispatch = next(
        item.kwargs["dispatch"] for item in log_app.user_middleware if "dispatch" in item.kwargs
    )
    prior_id, incoming_id = str(uuid4()), str(uuid4())

    async def run():
        token = request_id_context.set(prior_id)
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/context-test",
                "query_string": b"",
                "headers": [(b"x-request-id", incoming_id.encode())],
                "app": log_app,
            }
        )

        async def call_next(request):
            assert request_id_context.get() == incoming_id
            if cancel:
                raise asyncio.CancelledError
            return Response(status_code=200)

        try:
            if cancel:
                with pytest.raises(asyncio.CancelledError):
                    await dispatch(request, call_next)
            else:
                assert (await dispatch(request, call_next)).status_code == 200
            assert request_id_context.get() == prior_id
        finally:
            request_id_context.reset(token)

    asyncio.run(run())
