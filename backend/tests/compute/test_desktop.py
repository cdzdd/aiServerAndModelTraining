import asyncio
import importlib
import inspect
import json
import subprocess
import sys
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

pytestmark = pytest.mark.anyio
TOKEN = "desktop-secret-never-log"
JOB = str(uuid4())


@pytest.fixture
def anyio_backend():
    return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}


@pytest.fixture
def desktop():
    class MissingImplementation:
        def __getattr__(self, name):
            try:
                return getattr(importlib.import_module("app.modules.compute.desktop"), name)
            except ModuleNotFoundError:
                pytest.fail("desktop worker implementation is missing", pytrace=False)

    return MissingImplementation()


@asynccontextmanager
async def server(respond):
    requests, tasks, writers = [], set(), set()
    disconnected = asyncio.Event()

    async def handle(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        writers.add(writer)
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            lines = header.decode().split("\r\n")
            headers = dict(line.split(": ", 1) for line in lines[1:] if ": " in line)
            body = json.loads(await reader.readexactly(int(headers.get("Content-Length", 0))))
            path = lines[0].split()[1]
            requests.append((path, headers, body))
            response = respond(path, body)
            if inspect.isawaitable(response):
                response = await response
            if response is None:
                await reader.read()
                return
            status, raw, hold = response
            redirect = "Location: /redirect-must-not-be-followed\r\n" if status == 302 else ""
            writer.write(
                (
                    f"HTTP/1.1 {status} Test\r\n{redirect}Connection: close\r\n"
                    "Content-Type: application/x-ndjson\r\n"
                    "Transfer-Encoding: chunked\r\n\r\n"
                ).encode()
            )
            await writer.drain()
            if raw:
                writer.write(f"{len(raw):x}\r\n".encode() + raw + b"\r\n")
                await writer.drain()
            if hold:
                await reader.read()
            else:
                writer.write(b"0\r\n\r\n")
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            disconnected.set()
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
            writers.discard(writer)
            tasks.discard(task)

    listener = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        yield f"http://127.0.0.1:{listener.sockets[0].getsockname()[1]}", requests, disconnected
    finally:
        listener.close()
        for writer in list(writers):
            writer.close()
        pending = list(tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await listener.wait_closed()


def response(value, status=200):
    return status, json.dumps(value, ensure_ascii=False).encode(), False


def claim(*, seconds=30, **overrides):
    value = {
        "job_id": JOB,
        "lease_token": "lease-token",
        "deadline": (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(),
        "payload": {
            "model_id": "pinned-model",
            "messages": [{"role": "user", "content": "你好"}],
            "max_tokens": 32,
            "temperature": 0.3,
        },
    }
    value.update(overrides)
    return {"job": value}


def config(desktop, cloud, model):
    return desktop.DesktopConfig(
        cloud_url=cloud,
        token=TOKEN,
        model_id="pinned-model",
        model_base_url=model,
        ollama_num_ctx=4096,
    )


def frame(text="answer", reason="stop", **extra):
    return (
        json.dumps(
            {"message": {"content": text}, "done": True, "done_reason": reason, **extra}
        ).encode()
        + b"\n"
    )


async def test_no_job_and_cli_needs_no_database(desktop, tmp_path, monkeypatch):
    async with server(lambda *_: response({"job": None})) as (cloud, requests, _):
        cfg = config(desktop, cloud, "http://127.0.0.1:1")
        path = tmp_path / "desktop.json"
        path.write_text(cfg.model_dump_json())
        monkeypatch.setenv("DATABASE_URL", "invalid-database")
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
        process = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "app.modules.compute.desktop", "--config", str(path), "--once"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    assert process.returncode == 0, process.stderr.decode()
    assert len(requests) == 1
    assert requests[0][0] == "/internal/compute/claim"
    assert requests[0][1]["Authorization"] == f"Bearer {TOKEN}"
    assert requests[0][2] == {}
    assert TOKEN.encode() not in process.stdout + process.stderr


@pytest.mark.parametrize(
    "reason,usage,want_usage",
    [
        ("stop", {}, None),
        (
            "length",
            {"prompt_eval_count": 7, "eval_count": 4},
            {"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": None},
        ),
    ],
)
async def test_success_preserves_complete_text_reason_usage(
    desktop, reason, usage, want_usage, monkeypatch
):
    monkeypatch.setenv("MODEL_PROVIDER", "cloud")
    monkeypatch.setenv("MODEL_DISABLE_THINKING", "true")
    async with server(lambda *_: (200, frame("答案🌍", reason, **usage), False)) as (
        model,
        calls,
        _,
    ):
        async with server(
            lambda path, _: response(claim()) if path.endswith("/claim") else response(None, 204)
        ) as (cloud, requests, _):
            await desktop.run_node(config(desktop, cloud, model), once=True)
    assert len(calls) == 1
    assert calls[0][0] == "/api/chat"
    assert calls[0][2] == {
        "model": "pinned-model",
        "messages": [{"role": "user", "content": "你好"}],
        "stream": True,
        "truncate": False,
        "shift": False,
        "options": {"num_predict": 32, "temperature": 0.3, "num_ctx": 4096},
    }
    assert "Authorization" not in calls[0][1]
    assert requests[-1][0] == f"/internal/compute/{JOB}/result"
    assert requests[-1][2] == {
        "lease_token": "lease-token",
        "result": {
            "model_id": "pinned-model",
            "text": "答案🌍",
            "finish_reason": reason,
            "usage": want_usage,
        },
    }


@pytest.mark.parametrize(
    "value",
    [
        {"job": None, "command": "unexpected"},
        claim(
            payload={
                "model_id": "evil-model",
                "messages": [{"role": "user", "content": "x"}],
                "max_tokens": 32,
                "temperature": 0.3,
            }
        ),
        claim(job_id="../../outside"),
        claim(
            payload={
                "model_id": "pinned-model",
                "messages": [{"role": "user", "content": "x" * 12001}],
                "max_tokens": 32,
                "temperature": 0.3,
            }
        ),
        claim(
            payload={
                "model_id": "pinned-model",
                "messages": [{"role": "user", "content": "x"}],
                "max_tokens": 513,
                "temperature": 0.3,
            }
        ),
    ],
)
async def test_invalid_claim_never_calls_model_or_reclaims(desktop, value):
    async with server(lambda *_: (200, frame(), False)) as (model, calls, _):
        async with server(lambda *_: response(value)) as (cloud, requests, _):
            with pytest.raises(desktop.NodeError):
                await desktop.run_node(config(desktop, cloud, model))
    assert not calls
    assert len(requests) == 1


@pytest.mark.parametrize("status", [302, 401, 403, 500])
async def test_cloud_error_stops_without_replay_or_secret(desktop, status):
    async with server(lambda *_: response({"secret": TOKEN}, status)) as (cloud, requests, _):
        with pytest.raises(desktop.NodeError) as error:
            await desktop.run_node(config(desktop, cloud, "http://127.0.0.1:1"))
    assert TOKEN not in str(error.value)
    assert len(requests) == 1


async def test_oversized_cloud_body_stops(desktop):
    async with server(lambda *_: (200, b" " * 65537, False)) as (cloud, requests, _):
        with pytest.raises(desktop.NodeError):
            await desktop.run_node(config(desktop, cloud, "http://127.0.0.1:1"))
    assert len(requests) == 1


@pytest.mark.parametrize(
    "raw,status,code",
    [
        (frame("x" * 8193), 200, "PROVIDER_PROTOCOL_ERROR"),
        (b"private error", 302, "PROVIDER_BAD_REQUEST"),
        (b"private error", 401, "PROVIDER_AUTH_FAILED"),
        (b"{invalid secret}\n", 200, "PROVIDER_PROTOCOL_ERROR"),
    ],
)
async def test_local_failure_reports_sanitized_error_once_and_exits(desktop, raw, status, code):
    async with server(lambda *_: (status, raw, False)) as (model, calls, _):
        async with server(
            lambda path, _: response(claim()) if path.endswith("/claim") else response(None, 204)
        ) as (cloud, requests, _):
            with pytest.raises(desktop.NodeError):
                await desktop.run_node(config(desktop, cloud, model))
    assert len(calls) == 1
    assert len(requests) == 2
    assert requests[-1][2]["result"] == {"error_code": code}


async def test_failed_result_ack_is_not_replayed(desktop):
    async with server(lambda *_: (200, frame(), False)) as (model, calls, _):
        async with server(
            lambda path, _: (
                response(claim()) if path.endswith("/claim") else response({"error": TOKEN}, 500)
            )
        ) as (cloud, requests, _):
            with pytest.raises(desktop.NodeError):
                await desktop.run_node(config(desktop, cloud, model))
    assert len(calls) == 1
    assert len(requests) == 2


@pytest.mark.parametrize("stop", ["deadline", "heartbeat", "cancel", "lease"])
async def test_interrupted_generation_closes_socket_and_never_reclaims(desktop, stop):
    async def cloud_response(path, _):
        if path.endswith("/claim"):
            if stop == "lease":
                await asyncio.sleep(3)
            return response(claim(seconds=0.2 if stop == "deadline" else 30))
        if stop == "lease":
            return None
        return response({"error": "cancelled"}, 409)

    async with server(
        lambda *_: (200, b'{"done":false,"message":{"content":"partial"}}\n', True)
    ) as (model, calls, disconnected):
        async with server(cloud_response) as (cloud, requests, _):
            task = asyncio.create_task(desktop.run_node(config(desktop, cloud, model)))
            if stop == "cancel":
                while not calls:
                    await asyncio.sleep(0.01)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(desktop.NodeError):
                    await asyncio.wait_for(task, 17)
            await asyncio.wait_for(disconnected.wait(), 1)
    assert len(calls) == 1
    assert sum(path.endswith("/claim") for path, _, _ in requests) == 1
    assert not any(path.endswith("/result") for path, _, _ in requests)
    if stop in ("heartbeat", "lease"):
        assert requests[1][0] == f"/internal/compute/{JOB}/heartbeat"
        assert requests[1][2] == {"lease_token": "lease-token"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("cloud_url", "http://example.com"),
        ("cloud_url", "https://user:secret@example.com"),
        ("cloud_url", "https://example.com/path"),
        ("cloud_url", "https://example.com?token=secret"),
        ("model_base_url", "https://example.com"),
        ("model_base_url", "http://host.docker.internal"),
        ("model_base_url", "http://127.0.0.1/other"),
        ("token", "secret\nheader"),
        ("model_id", "model\ncommand"),
    ],
)
async def test_invalid_private_config_is_sanitized(desktop, tmp_path, field, value):
    data = {
        "cloud_url": "https://example.com",
        "token": TOKEN,
        "model_id": "pinned-model",
        "model_base_url": "http://127.0.0.1",
        "ollama_num_ctx": 4096,
    }
    data[field] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    with pytest.raises(desktop.NodeError) as error:
        desktop.load_config(path)
    assert TOKEN not in str(error.value)


async def test_successful_heartbeat_runs_during_slow_local_generation(desktop):
    async def slow_model(*_):
        await asyncio.sleep(5.2)
        return 200, frame(), False

    async with server(slow_model) as (model, calls, _):
        async with server(
            lambda path, _: response(claim()) if path.endswith("/claim") else response(None, 204)
        ) as (cloud, requests, _):
            await desktop.run_node(config(desktop, cloud, model), once=True)
    assert len(calls) == 1
    assert [path for path, _, _ in requests] == [
        "/internal/compute/claim",
        f"/internal/compute/{JOB}/heartbeat",
        f"/internal/compute/{JOB}/result",
    ]


async def test_normal_loop_waits_one_second_after_results_before_next_serial_claim(desktop):
    claims, result_times, claim_times = [], [], []
    loop = asyncio.get_running_loop()

    def cloud_response(path, _):
        if path.endswith("/claim"):
            claim_times.append(loop.time())
            if len(claim_times) > 2:
                return response({"error": "stop test"}, 401)
            claims.append(str(uuid4()))
            return response(claim(job_id=claims[-1]))
        result_times.append(loop.time())
        return response(None, 204)

    async with server(lambda *_: (200, frame(), False)) as (model, calls, _):
        async with server(cloud_response) as (cloud, requests, _):
            with pytest.raises(desktop.NodeError):
                await desktop.run_node(config(desktop, cloud, model))
    assert len(calls) == 2
    assert len(requests) == 5
    assert len(result_times) == 2
    assert claim_times[1] - result_times[0] >= 0.9
    assert claim_times[2] - result_times[1] >= 0.9
    assert [path for path, _, _ in requests] == [
        "/internal/compute/claim",
        f"/internal/compute/{claims[0]}/result",
        "/internal/compute/claim",
        f"/internal/compute/{claims[1]}/result",
        "/internal/compute/claim",
    ]
