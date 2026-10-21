import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from app.core.errors import error_response
from app.core.security import AuthError
from tests.compute.test_queue import new_scope, payload, result


@pytest.fixture
def api(migrated_engine):
    from app.modules.compute.limits import ComputeBodyLimitMiddleware
    from app.modules.compute.models import ComputeJob
    from app.modules.compute.router import router
    from app.modules.compute.service import enqueue, register_worker

    app = FastAPI()
    factory = sessionmaker(migrated_engine, expire_on_commit=False)
    now = datetime.now(UTC)
    app.state.session_factory = factory
    app.state.auth_clock = lambda: now
    app.add_middleware(ComputeBodyLimitMiddleware)
    app.include_router(router)

    @app.middleware("http")
    async def context(request, call_next):
        request.state.request_id = "test-request"
        return await call_next(request)

    @app.exception_handler(AuthError)
    async def auth_error(request, exc):
        return error_response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return error_response(request, 422, "VALIDATION_ERROR", "Invalid parameters")

    with factory.begin() as db:
        db.execute(delete(ComputeJob))
        scope = new_scope(db, now)
        worker, token = register_worker(db, name="test", model_id="test-model", now=now)
        enqueue(db, scope, payload(), now=now)
    return app, factory, worker, token


def test_machine_cookie_cannot_replace_bearer(api):
    app, _, _, token = api
    with TestClient(app) as client:
        client.cookies.set("qa_session", token)
        for authorization in [None, "Basic " + token, "Bearer wrong"]:
            headers = {"Authorization": authorization} if authorization else {}
            response = client.post("/internal/compute/claim", json={}, headers=headers)
            assert response.status_code == 401
            assert response.headers["cache-control"] == "no-store"
            assert token not in response.text


def test_fixed_machine_routes_and_worker_revocation(api):
    from app.modules.compute.models import ComputeWorker

    app, factory, worker, token = api
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + token}
        response = client.post("/internal/compute/claim", json={}, headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        claim = response.json()["job"]
        assert set(claim) == {"job_id", "lease_token", "deadline", "payload"}
        lease = {"lease_token": claim["lease_token"]}
        url = "/internal/compute/" + claim["job_id"]
        assert client.post(url + "/heartbeat", json=lease, headers=headers).status_code == 204
        assert (
            client.post(
                url + "/result", json=lease | {"result": result()}, headers=headers
            ).status_code
            == 204
        )
        assert client.post("/internal/compute/claim", json={}, headers=headers).json() == {
            "job": None
        }
        with factory.begin() as db:
            db.get(ComputeWorker, worker.id).is_active = False
        response = client.post(url + "/result", json=lease | {"result": result()}, headers=headers)
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("body", [{"extra": "private-secret"}, None, []])
def test_claim_body_strict_and_errors_do_not_echo(api, body):
    app, _, _, token = api
    with TestClient(app) as client:
        response = client.post(
            "/internal/compute/claim",
            content=json.dumps(body),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert response.headers["cache-control"] == "no-store"
        assert "private-secret" not in response.text


def test_actual_chunked_bytes_are_limited_before_dispatch():
    from app.modules.compute.limits import ComputeBodyLimitMiddleware

    invoked = []

    async def downstream(scope, receive, send):
        invoked.append(True)
        await receive()

    async def run():
        chunks = iter(
            [
                {"type": "http.request", "body": b"x" * 40000, "more_body": True},
                {"type": "http.request", "body": b"y" * 30000, "more_body": False},
            ]
        )
        sent = []

        async def receive():
            return next(chunks)

        async def send(message):
            sent.append(message)

        await ComputeBodyLimitMiddleware(downstream)(
            {
                "type": "http",
                "path": "/internal/compute/claim",
                "method": "POST",
                "headers": [(b"content-length", b"1")],
                "state": {"request_id": "test"},
            },
            receive,
            send,
        )
        assert sent[0]["status"] == 413
        assert (b"cache-control", b"no-store") in sent[0]["headers"]
        assert b"xxxx" not in sent[1]["body"]

    asyncio.run(run())
    assert not invoked


def test_limit_exact_boundary_and_prefix():
    from app.modules.compute.limits import ComputeBodyLimitMiddleware

    seen = []

    async def downstream(scope, receive, send):
        body = await receive()
        seen.append(len(body["body"]))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def run(path, size):
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"x" * size, "more_body": False}

        async def send(message):
            sent.append(message)

        await ComputeBodyLimitMiddleware(downstream)(
            {"type": "http", "path": path, "method": "POST", "headers": []}, receive, send
        )
        return sent

    response = asyncio.run(run("/internal/compute/claim", 65536))
    assert response[0]["status"] == 200
    assert (b"cache-control", b"no-store") in response[0]["headers"]
    asyncio.run(run("/internal/computeevil", 70000))
    assert seen == [65536, 70000]


def test_secret_file_is_new_and_not_echoed(tmp_path, capsys):
    from app.modules.compute.manage import write_private_config

    path = tmp_path / "desktop.json"
    write_private_config(path, {"token": "private-machine-secret"})
    assert json.loads(path.read_text())["token"] == "private-machine-secret"
    with pytest.raises(FileExistsError):
        write_private_config(path, {"token": "replacement"})
    assert "private-machine-secret" not in capsys.readouterr().out
    if __import__("os").name != "nt":
        assert path.stat().st_mode & 0o077 == 0
    else:
        import subprocess

        permissions = subprocess.run(
            ["icacls", str(path)], check=True, capture_output=True, text=True
        ).stdout
        assert "(I)" not in permissions and "(F)" in permissions


def test_management_cli_registers_and_revokes_only_its_machine(
    migrated_engine, tmp_path, monkeypatch, capsys
):
    from app.core.security import token_hash
    from app.modules.compute.manage import main
    from app.modules.compute.models import ComputeWorker
    from app.modules.compute.service import authenticate_worker

    monkeypatch.setenv("DATABASE_URL", migrated_engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("SESSION_SECRET", "compute-cli-test-secret")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    destination = tmp_path / "node.json"
    args = [
        "register",
        "--name",
        "cli-test",
        "--model-id",
        "test-model",
        "--cloud-url",
        "http://127.0.0.1:15472",
        "--output",
        str(destination),
    ]
    main(args)
    config = json.loads(destination.read_text())
    assert set(config) == {"cloud_url", "token", "model_id", "model_base_url", "ollama_num_ctx"}
    assert config["token"] not in capsys.readouterr().out
    factory = sessionmaker(migrated_engine)
    with factory() as db:
        worker = authenticate_worker(db, config["token"], now=datetime.now(UTC))
        worker_id = worker.id
        assert worker.token_hash == token_hash(config["token"])
    with pytest.raises(FileExistsError):
        main(args)
    assert json.loads(destination.read_text()) == config
    main(["revoke", "--worker-id", str(worker_id)])
    with factory() as db:
        assert not db.get(ComputeWorker, worker_id).is_active
        with pytest.raises(AuthError) as exc:
            authenticate_worker(db, config["token"], now=datetime.now(UTC))
        assert exc.value.status == 401
    assert config["token"] not in capsys.readouterr().out


@pytest.mark.parametrize(
    "lock_kind", ["advisory", "user", "session", "conversation", "message", "worker"]
)
@pytest.mark.parametrize("operation", ["heartbeat", "result", "duplicate", "claim", "session"])
def test_live_machine_clock_is_sampled_after_contention(api, lock_kind, operation):
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue
    from threading import Event
    from time import monotonic

    from sqlalchemy import select, text

    from app.modules.auth.models import AuthSession, User
    from app.modules.chat.models import Conversation, Message
    from app.modules.compute.models import ComputeJob, ComputeWorker

    app, factory, worker, token = api
    initial = app.state.auth_clock()
    clock = [initial]
    app.state.auth_clock = lambda: clock[0]
    headers = {"Authorization": "Bearer " + token}
    with factory() as db:
        job = db.scalar(select(ComputeJob))
        job_id, actor_id, message_id, session_hash = (
            job.id,
            job.actor_id,
            job.assistant_message_id,
            job.session_hash,
        )
    with TestClient(app) as client:
        if operation != "claim":
            if operation in {"result", "duplicate"}:
                clock[0] = initial + timedelta(seconds=54)
            claimed = client.post("/internal/compute/claim", json={}, headers=headers).json()["job"]
            body = {"lease_token": claimed["lease_token"]}
            suffix = "heartbeat"
            if operation in {"result", "duplicate"}:
                suffix, body = "result", body | {"result": result()}
            url = f"/internal/compute/{job_id}/{suffix}"
            if operation == "duplicate":
                assert client.post(url, json=body, headers=headers).status_code == 204
            before, after = (14, 16) if operation == "heartbeat" else (59, 61)
            if operation == "session":
                before, after = 9, 11
                with factory.begin() as db:
                    session = db.scalar(
                        select(AuthSession).where(AuthSession.token_hash == session_hash)
                    )
                    session.expires_at = initial + timedelta(seconds=10)
        else:
            url, body, before, after = "/internal/compute/claim", {}, 59, 61
        clock[0] = initial + timedelta(seconds=before)
        pids = Queue()

        def tracked_factory():
            db = factory()
            pids.put(db.scalar(text("SELECT pg_backend_pid()")))
            return db

        app.state.session_factory = tracked_factory
        with ThreadPoolExecutor(max_workers=1) as pool:
            with factory.begin() as blocker:
                if lock_kind == "advisory":
                    blocker.execute(text("SELECT pg_advisory_xact_lock(2021, 1)"))
                else:
                    if lock_kind == "session":
                        blocker.scalar(
                            select(AuthSession)
                            .where(AuthSession.token_hash == session_hash)
                            .with_for_update()
                        )
                    else:
                        model, identity = {
                            "user": (User, actor_id),
                            "message": (Message, message_id),
                            "conversation": (Conversation, job.conversation_id),
                            "worker": (ComputeWorker, worker.id),
                        }[lock_kind]
                        blocker.scalar(select(model).where(model.id == identity).with_for_update())
                pending = pool.submit(client.post, url, json=body, headers=headers)
                pid = pids.get(timeout=5)
                waiting = False
                limit = monotonic() + 5
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
                clock[0] = initial + timedelta(seconds=after)
            response = pending.result(timeout=5)
        if operation == "claim":
            assert response.status_code == 200
            assert response.json() == {"job": None}
        else:
            assert response.status_code == 409
