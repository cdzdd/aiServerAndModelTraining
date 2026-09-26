import asyncio
import json
import threading
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.modules.knowledge.models import KnowledgeBase
from app.modules.rag.schemas import AnswerEvent


def reply(usage=None):
    return [
        AnswerEvent(type="delta", payload={"text": "当前资料中没有依据。"}),
        AnswerEvent(type="citations", payload={"items": []}),
        AnswerEvent(
            type="done",
            payload={
                "answer_status": "no_answer",
                "evidence_level": "none",
                "intent": "knowledge",
                "usage": usage,
            },
        ),
    ]


class ScriptedRAG:
    def __init__(self, events=None, *, hold=False, before_event=None):
        self.events = reply() if events is None else events
        self.hold = hold
        self.before_event = before_event
        self.started, self.closed = threading.Event(), threading.Event()
        self.calls = 0

    async def stream_answer(self, actor, kb_ids, question, history):
        self.calls += 1
        self.started.set()
        try:
            for event in self.events:
                if self.before_event:
                    self.before_event(event)
                if isinstance(event, Exception):
                    raise event
                yield event
            if self.hold:
                await asyncio.Event().wait()
        finally:
            self.closed.set()


@pytest.fixture
def stream_app(migrated_engine, tmp_path):
    from app.main import create_app

    app = create_app(
        Settings(
            _env_file=None,
            APP_ENV="test",
            DATABASE_URL=migrated_engine.url.render_as_string(hide_password=False),
            SESSION_SECRET="chat-stream-test-secret-at-least32",
            UPLOAD_DIR=tmp_path,
        )
    )
    app.state.chat_rag = ScriptedRAG()
    with app.state.session_factory() as db:
        kb = KnowledgeBase(name="stream-fixture", visibility="public")
        db.add(kb)
        db.commit()
        app.state.test_kb_id = kb.id
    yield app
    app.state.engine.dispose()


@pytest.fixture
def stream_client(stream_app):
    with TestClient(stream_app, base_url="http://testserver") as client:
        yield client


def sign_in(client):
    username = "stream-" + uuid4().hex[:12]
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    headers = {"Origin": str(client.base_url).rstrip("/"), "X-CSRF-Token": csrf}
    data = {"username": username, "password": "a-chat-test-password-123"}
    user = client.post(
        "/api/v1/auth/register", json={**data, "display_name": "用户"}, headers=headers
    )
    assert user.status_code == 201, user.text
    login = client.post("/api/v1/auth/login", json=data, headers=headers)
    assert login.status_code == 200, login.text
    headers["X-CSRF-Token"] = login.json()["csrf_token"]
    return user.json(), headers


def conversation(client, app, headers):
    result = client.post(
        "/api/v1/conversations", headers=headers, json={"kb_ids": [str(app.state.test_kb_id)]}
    )
    assert result.status_code == 201, result.text
    return result.json()["id"]


def send(client, cid, headers, key=None):
    return client.post(
        f"/api/v1/conversations/{cid}/messages/stream",
        headers=headers,
        json={"content": "图书馆几点开门？", "client_message_id": str(key or uuid4())},
    )


def parse_sse(text):
    parsed = []
    for block in text.strip().split("\n\n"):
        lines = block.splitlines()
        parsed.append(
            (lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: ")))
        )
    return parsed


def assistant(app, cid):
    from app.modules.chat.models import Message

    with app.state.session_factory() as db:
        return db.scalar(
            select(Message).where(Message.conversation_id == UUID(cid), Message.role == "assistant")
        )
