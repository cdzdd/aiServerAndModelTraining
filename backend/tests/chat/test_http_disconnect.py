import asyncio
import json
import socket
import threading
import time
from contextlib import contextmanager
from uuid import uuid4

import httpx2
import pytest
import uvicorn
from chat_stream_helpers import (
    ScriptedRAG,
    assistant,
    conversation,
    reply,
    sign_in,
)
from chat_stream_helpers import stream_app as stream_app


@contextmanager
def live_server(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, access_log=False, log_level="error", lifespan="on"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started, "Local HTTP app failed to start"
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive(), "Local HTTP app did not shut down"


def read_event(lines):
    kind = None
    payload = None
    for line in lines:
        if line.startswith("event: "):
            kind = line[7:]
        elif line.startswith("data: "):
            payload = json.loads(line[6:])
        elif not line and kind is not None:
            return kind, payload
    raise AssertionError("Stream ended before a complete event")


def wait_cancelled(app, cid):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        message = assistant(app, cid)
        if message and message.status == "cancelled":
            return message
        time.sleep(0.01)
    raise AssertionError("Disconnected request was not persisted as cancelled")


@pytest.mark.parametrize("after_delta", [False, True])
def test_real_http_disconnect_closes_upstream_and_persists_cancelled(stream_app, after_delta):
    rag = ScriptedRAG(reply()[:2] if after_delta else [], hold=True)
    stream_app.state.chat_rag = rag
    with live_server(stream_app) as url, httpx2.Client(base_url=url, timeout=5) as client:
        _, headers = sign_in(client)
        cid = conversation(client, stream_app, headers)
        path = f"/api/v1/conversations/{cid}/messages/stream"
        with client.stream(
            "POST",
            path,
            headers=headers,
            json={"content": "图书馆几点开放？", "client_message_id": str(uuid4())},
        ) as response:
            assert response.status_code == 200
            lines = response.iter_lines()
            kind, metadata = read_event(lines)
            assert kind == "meta"
            assert str(assistant(stream_app, cid).id) == metadata["assistant_message_id"]
            assert rag.started.wait(2)
            if after_delta:
                assert read_event(lines)[0] == "delta"
        assert rag.closed.wait(2), "Closing HTTP must cancel the blocked RAG await"
        saved = wait_cancelled(stream_app, cid)
        assert saved.content == ("当前资料中没有依据。" if after_delta else "")
        stream_app.state.chat_rag = ScriptedRAG()
        again = client.post(
            path,
            headers=headers,
            json={"content": "图书馆在哪里？", "client_message_id": str(uuid4())},
        )
        assert again.status_code == 200
        assert "event: done" in again.text


def test_real_http_disconnect_before_first_delta_closes_actual_provider(stream_app):
    from app.modules.providers.schemas import LLMDelta
    from app.modules.rag.service import RAGService
    from app.modules.retrieval.schemas import SearchHit

    started, closed = threading.Event(), threading.Event()

    class Provider:
        async def stream(self, messages, *, max_tokens, temperature):
            try:
                started.set()
                yield LLMDelta(text='{"status":')
                await asyncio.Event().wait()
            finally:
                closed.set()

    async def search(actor, kb_ids, query, top_k=5):
        return [
            SearchHit(
                chunk_id=uuid4(),
                kb_id=kb_ids[0],
                text="图书馆九点开放。",
                source_type="document",
                source_id=uuid4(),
                revision_id=uuid4(),
                title="指南",
                score=0.9,
            )
        ]

    async def validate(actor, kb_ids, hits):
        return True

    stream_app.state.chat_rag = RAGService(search, validate, Provider())
    with live_server(stream_app) as url, httpx2.Client(base_url=url, timeout=5) as client:
        _, headers = sign_in(client)
        cid = conversation(client, stream_app, headers)
        with client.stream(
            "POST",
            f"/api/v1/conversations/{cid}/messages/stream",
            headers=headers,
            json={"content": "图书馆几点开放？", "client_message_id": str(uuid4())},
        ) as response:
            lines = response.iter_lines()
            assert read_event(lines)[0] == "meta"
            assert started.wait(2)
            assert not closed.is_set()
        assert closed.wait(2)
        assert wait_cancelled(stream_app, cid).content == ""


def test_real_http_global_and_conversation_limits_do_not_start_extra_rag(stream_app):
    from contextlib import ExitStack

    rag = ScriptedRAG([], hold=True)
    stream_app.state.chat_rag = rag
    with live_server(stream_app) as url, httpx2.Client(base_url=url, timeout=5) as client:
        _, headers = sign_in(client)
        ids = [conversation(client, stream_app, headers) for _ in range(3)]
        keys = [str(uuid4()), str(uuid4())]
        with ExitStack() as active:
            active_readers = []
            for cid, key in zip(ids[:2], keys, strict=True):
                response = active.enter_context(
                    client.stream(
                        "POST",
                        f"/api/v1/conversations/{cid}/messages/stream",
                        headers=headers,
                        json={"content": "图书馆在哪？", "client_message_id": key},
                    )
                )
                assert response.status_code == 200
                active_readers.append(response.iter_lines())
                assert read_event(active_readers[-1])[0] == "meta"
            extra = client.post(
                f"/api/v1/conversations/{ids[2]}/messages/stream",
                headers=headers,
                json={"content": "图书馆在哪？", "client_message_id": str(uuid4())},
            )
            assert extra.status_code == 429
            conflict = client.post(
                f"/api/v1/conversations/{ids[0]}/messages/stream",
                headers=headers,
                json={"content": "图书馆在哪？", "client_message_id": str(uuid4())},
            )
            assert conflict.status_code == 409
            duplicate = client.post(
                f"/api/v1/conversations/{ids[0]}/messages/stream",
                headers=headers,
                json={"content": "图书馆在哪？", "client_message_id": keys[0]},
            )
            assert duplicate.status_code == 409
            assert duplicate.json()["error"]["details"][0]["assistant_message_id"]
            assert rag.calls == 2
        for cid in ids[:2]:
            wait_cancelled(stream_app, cid)
