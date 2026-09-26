import asyncio
import json
import socket
import threading
import time
from contextlib import contextmanager
from uuid import UUID, uuid4

import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.auth.models import User
from app.modules.chat.models import Conversation
from app.modules.handoff.models import Handoff
from app.modules.providers.schemas import LLMDelta
from app.modules.rag.service import RAGService
from app.modules.retrieval.service import RetrievalService
from tests.chat.chat_stream_helpers import assistant, conversation, sign_in
from tests.chat.chat_stream_helpers import stream_app as stream_app
from tests.retrieval.search_helpers import FixedEmbedder, SearchData


@contextmanager
def live_server(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=port, access_log=False, log_level="error", lifespan="on"
        )
    )
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive(), "HTTP test server did not stop"


def read_event(lines):
    kind, payload = None, None
    for line in lines:
        if line.startswith("event: "):
            kind = line[7:]
        elif line.startswith("data: "):
            payload = json.loads(line[6:])
        elif not line and kind:
            return kind, payload
    raise AssertionError("Expected SSE event")


class HeldProvider:
    def __init__(self):
        self.started, self.closed = threading.Event(), threading.Event()
        self.calls = 0

    async def stream(self, messages, *, max_tokens, temperature):
        self.calls += 1
        try:
            yield LLMDelta(text='{"status":"answered"')
            self.started.set()
            await asyncio.Event().wait()
        finally:
            self.closed.set()


def test_real_http_handoff_commits_then_cancels_real_rag_provider(stream_app):
    data = SearchData(stream_app.state.session_factory)
    data.document(stream_app.state.test_kb_id, text="图书馆九点开放。")
    retrieval = RetrievalService(data.factory, FixedEmbedder())
    provider = HeldProvider()
    stream_app.state.chat_rag = RAGService(retrieval.search, retrieval.validate_hits, provider)
    cancelled_states = []
    real_cancel = stream_app.state.chat_runtime.cancel

    def observe_cancel(cid):
        with data.factory() as db:
            cancelled_states.append(db.get(Conversation, cid).mode)
        real_cancel(cid)

    stream_app.state.chat_runtime.cancel = observe_cancel
    with live_server(stream_app) as url, httpx2.Client(base_url=url, timeout=5) as client:
        _, headers = sign_in(client)
        cid = conversation(client, stream_app, headers)
        with client.stream(
            "POST",
            f"/api/v1/conversations/{cid}/messages/stream",
            headers=headers,
            json={"content": "图书馆几点开放？", "client_message_id": str(uuid4())},
        ) as response:
            assert response.status_code == 200
            lines = response.iter_lines()
            assert read_event(lines)[0] == "meta"
            assert provider.started.wait(3)
            with httpx2.Client(base_url=url, cookies=client.cookies, timeout=5) as control:
                result = control.post(f"/api/v1/conversations/{cid}/handoff", headers=headers)
                assert result.status_code == 201, result.text
                assert result.json()["state"] == "queued"
                assert assistant(stream_app, cid).status == "cancelled"
            assert provider.closed.wait(3)
            trailing = "\n".join(lines)
            assert "event: done" not in trailing
            assert "event: delta" not in trailing
        assert cancelled_states == ["queued"]
        assert provider.calls == 1
        assert assistant(stream_app, cid).status == "cancelled"


def set_role(app, user, role):
    with app.state.session_factory() as db:
        db.get(User, UUID(user["id"])).role = role
        db.commit()


def test_http_roles_human_messages_never_call_rag_and_close_readonly(stream_app):
    with (
        live_server(stream_app) as url,
        httpx2.Client(base_url=url) as owner,
        httpx2.Client(base_url=url) as agent,
        httpx2.Client(base_url=url) as other,
    ):
        _, owner_headers = sign_in(owner)
        user, agent_headers = sign_in(agent)
        set_role(stream_app, user, "agent")
        loser, other_headers = sign_in(other)
        set_role(stream_app, loser, "agent")
        cid = conversation(owner, stream_app, owner_headers)
        path = f"/api/v1/conversations/{cid}"
        result = owner.post(path + "/handoff", headers=owner_headers)
        hid = result.json()["id"]
        assert owner.post(path + "/handoff", headers=owner_headers).status_code == 200
        assert agent.get(path + "/messages").status_code == 404
        queue = agent.get("/api/v1/handoffs").json()["items"]
        assert set(next(item for item in queue if item["id"] == hid)) == {
            "id",
            "conversation_id",
            "requested_at",
            "state",
        }
        assert agent.post(f"/api/v1/handoffs/{hid}/claim", headers=agent_headers).status_code == 200
        assert other.post(f"/api/v1/handoffs/{hid}/claim", headers=other_headers).status_code == 409
        assert other.get(path + "/messages").status_code == 404
        for client, headers in ((owner, owner_headers), (agent, agent_headers)):
            sent = client.post(
                path + "/messages",
                headers=headers,
                json={"content": "人工消息", "client_message_id": str(uuid4())},
            )
            assert sent.status_code == 201, sent.text
        assert stream_app.state.chat_rag.calls == 0
        assert agent.post(f"/api/v1/handoffs/{hid}/close", headers=agent_headers).status_code == 200
        assert agent.get(path + "/messages").status_code == 200
        for suffix in ("/messages", "/messages/stream"):
            response = owner.post(
                path + suffix,
                headers=owner_headers,
                json={"content": "已关闭", "client_message_id": str(uuid4())},
            )
            assert response.status_code == 409
        assert stream_app.state.chat_rag.calls == 0


def test_failed_commit_does_not_cancel_or_leave_handoff(stream_app):
    cancelled = []
    stream_app.state.chat_runtime.cancel = cancelled.append
    with TestClient(stream_app, raise_server_exceptions=False) as client:
        _, headers = sign_in(client)
        cid = conversation(client, stream_app, headers)
        real_factory = stream_app.state.session_factory

        class FailedCommit(Session):
            def commit(self):
                raise OperationalError("commit", {}, Exception("synthetic commit failure"))

        stream_app.state.session_factory = sessionmaker(
            bind=stream_app.state.engine, class_=FailedCommit, expire_on_commit=False
        )
        result = client.post(f"/api/v1/conversations/{cid}/handoff", headers=headers)
        stream_app.state.session_factory = real_factory
        assert result.status_code == 500
        assert cancelled == []
        with real_factory() as db:
            assert db.get(Conversation, UUID(cid)).mode == "bot"
            assert db.scalar(select(Handoff).where(Handoff.conversation_id == UUID(cid))) is None


@pytest.mark.parametrize("path", ["/api/v1/handoffs", "/api/v1/handoffs?page=0"])
def test_queue_requires_login(stream_app, path):
    with TestClient(stream_app) as client:
        assert client.get(path).status_code == 401


def test_write_csrf_and_readiness_are_enforced(stream_app):
    with TestClient(stream_app) as client:
        user, headers = sign_in(client)
        cid = conversation(client, stream_app, headers)
        path = f"/api/v1/conversations/{cid}/handoff"
        assert client.post(path).status_code == 403
        stream_app.state.chat_ready = False
        assert client.post(path, headers=headers).status_code == 503
        stream_app.state.chat_ready = True
        handoff = client.post(path, headers=headers).json()
        set_role(stream_app, user, "agent")
        assert client.get("/api/v1/handoffs?page=0").status_code == 422
        assert client.get("/api/v1/handoffs?page_size=101").status_code == 422
        stream_app.state.chat_ready = False
        for action in ("claim", "close"):
            assert (
                client.post(
                    f"/api/v1/handoffs/{handoff['id']}/{action}", headers=headers
                ).status_code
                == 503
            )
