import json
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.core.security import verify_password
from app.modules.auth.models import AuthSession, User
from app.modules.chat.models import Conversation, GenerationUsage, Message
from app.modules.compute import service as compute
from app.modules.compute.context import generation_scope
from app.modules.compute.models import ComputeWorker
from app.modules.fund_assistant import service
from app.modules.fund_assistant.knowledge_contract import KB_DESCRIPTION, KB_NAME
from app.modules.fund_assistant.models import FundSubject
from app.modules.knowledge.models import FAQ, KnowledgeBase, KnowledgeMembership
from app.modules.providers.queued import QueuedProvider
from app.modules.providers.schemas import LLMMessage
from app.modules.rag.schemas import AnswerEvent
from tests.chat.chat_stream_helpers import ScriptedRAG, reply, sign_in
from tests.chat.test_app_startup import settings_for
from tests.conftest import migrated_engine as migrate_test_schema
from tests.retrieval.search_helpers import SearchData

PREFIX = "/internal/fund-assistant"
KEY = "test-fund-service-key-only-never-production"
MODEL = "fund-queue-test-model"


def test_optional_blank_environment_values_keep_integration_disabled(tmp_path):
    from app.core.config import Settings

    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="postgresql+psycopg://unused:unused@127.0.0.1:1/test",
        SESSION_SECRET="test-only",
        UPLOAD_DIR=tmp_path,
        FUND_ASSISTANT_SERVICE_KEY="",
        FUND_ASSISTANT_KB_ID="",
    )
    assert settings.fund_assistant_kb_id is None
    assert service.credential_digest(settings) is None


@pytest.fixture
def migrated_engine(database_url):
    # Background generation uses independent transactions and cannot share a test savepoint.
    yield from migrate_test_schema.__wrapped__(database_url)


@pytest.fixture
def bridge(migrated_engine, tmp_path):
    from app.main import create_app

    factory = sessionmaker(migrated_engine, expire_on_commit=False)
    data = SearchData(factory)
    kb_id = data.kb()
    with factory.begin() as db:
        kb = db.get(KnowledgeBase, kb_id)
        kb.name, kb.description = KB_NAME, KB_DESCRIPTION
    data.faq(kb_id)
    settings = settings_for(migrated_engine, tmp_path)
    settings.fund_assistant_service_key = SecretStr(KEY)
    settings.fund_assistant_kb_id = kb_id
    app = create_app(settings)
    app.state.chat_rag.provider = QueuedProvider(factory, model_id=MODEL, max_output_tokens=512)
    app.state.fund_assistant_rag = ScriptedRAG()
    with factory.begin() as db:
        worker, token = compute.register_worker(
            db, name="existing-desktop", model_id=MODEL, now=datetime.now(UTC)
        )
        worker.last_seen_at = datetime.now(UTC)
        worker_id = worker.id
    with TestClient(app) as client:
        yield app, client, factory, worker_id, token, data


def headers(subject="1"):
    return {"Authorization": "Bearer " + KEY, "X-Fund-User-Id": subject}


def create(client, subject="1"):
    response = client.post(PREFIX + "/conversations", json={}, headers=headers(subject))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def ask(client, conversation_id, *, subject="1", request_id=None, content="模拟申购如何操作？"):
    return client.post(
        PREFIX + f"/conversations/{conversation_id}/messages",
        json={"content": content, "requestId": request_id or str(uuid4())},
        headers=headers(subject),
    )


def finished(client, conversation_id, subject="1"):
    for _ in range(100):
        response = client.get(
            PREFIX + f"/conversations/{conversation_id}", headers=headers(subject)
        )
        assert response.status_code == 200, response.text
        result = response.json()
        if result["status"] in {"completed", "failed", "cancelled"}:
            return result
        time.sleep(0.02)
    pytest.fail("background generation did not settle")


def test_disabled_and_unauthenticated_integration_does_not_change_browser_csrf(bridge):
    app, client, _, _, _, _ = bridge
    assert client.get(PREFIX + "/status", headers={"X-Fund-User-Id": "1"}).status_code == 401
    assert client.get(PREFIX + "/status", headers=headers("0")).status_code == 422
    assert client.get(PREFIX + "/status", headers=headers("9223372036854775808")).status_code == 422
    assert client.post("/api/v1/conversations", json={}).status_code == 403
    app.state.settings.fund_assistant_service_key = None
    assert client.get(PREFIX + "/status", headers=headers()).status_code == 404
    assert client.get("/health/ready").status_code == 200
    assert client.get("/api/v1/auth/csrf").status_code == 200


def test_subjects_cannot_read_send_or_cancel_each_others_conversations(bridge):
    _, client, factory, _, _, data = bridge
    first = create(client)
    second = create(client, "2")
    wrong_kb = data.kb(visibility="public")
    bad_create = client.post(
        PREFIX + "/conversations", headers=headers(), json={"kb_ids": [str(wrong_kb)]}
    )
    assert bad_create.status_code == 422
    for operation, suffix, body in [
        ("get", "", None),
        ("post", "/cancel", {}),
        ("post", "/messages", {"content": "查看", "requestId": str(uuid4())}),
    ]:
        kwargs = {"headers": headers("2")}
        if body is not None:
            kwargs["json"] = body
        response = getattr(client, operation)(PREFIX + f"/conversations/{first}" + suffix, **kwargs)
        assert response.status_code == 404
    listed = client.get(PREFIX + "/conversations", headers=headers("2")).json()
    assert [item["id"] for item in listed["items"]] == [second]
    with factory() as db:
        subjects = list(db.scalars(select(FundSubject)))
        assert len({item.user_id for item in subjects}) == 2
        for item in subjects:
            user = db.get(User, item.user_id)
            assert user.role == "user"
            assert not verify_password(user.password_hash, "any-attempted-password-123")


def test_registered_shadow_username_cannot_be_registered_or_logged_in(bridge):
    _, client, factory, _, _, _ = bridge
    create(client)
    with factory() as db:
        mapping = db.get(FundSubject, "1")
        username = db.get(User, mapping.user_id).username
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    auth_headers = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
    password = "test-trying-to-take-over-shadow-123"
    result = client.post(
        "/api/v1/auth/register",
        headers=auth_headers,
        json={"username": username, "password": password, "display_name": "不能接管"},
    )
    assert result.status_code == 409
    result = client.post(
        "/api/v1/auth/login",
        headers=auth_headers,
        json={"username": username, "password": password},
    )
    assert result.status_code == 401


def test_asynchronous_idempotency_rejects_different_body_and_preserves_history(bridge):
    app, client, factory, _, _, _ = bridge
    app.state.fund_assistant_rag = ScriptedRAG(events=[], hold=True)
    conversation_id = create(client)
    request_id = str(uuid4())
    assert ask(client, conversation_id, request_id=request_id).status_code == 202
    assert ask(client, conversation_id, request_id=request_id).status_code == 202
    conflict = ask(client, conversation_id, request_id=request_id, content="不同问题")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "ASSISTANT_REQUEST_CONFLICT"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(GenerationUsage)) == 1
    assert (
        client.post(
            PREFIX + f"/conversations/{conversation_id}/cancel", headers=headers()
        ).status_code
        == 200
    )
    result = finished(client, conversation_id)
    assert result["status"] == "cancelled"
    assert len(result["messages"]) == 2


def test_offline_and_pending_knowledge_never_enqueue_and_keep_health_ready(bridge):
    _, client, factory, worker_id, _, _ = bridge
    conversation_id = create(client)
    with factory.begin() as db:
        db.get(ComputeWorker, worker_id).last_seen_at = datetime.now(UTC) - timedelta(seconds=31)
    current = client.get(PREFIX + "/status", headers=headers()).json()
    assert not current["available"] and current["reason"] == "offline"
    result = ask(client, conversation_id)
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "ASSISTANT_MODEL_OFFLINE"
    assert client.get("/health/ready").status_code == 200
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 0


def test_unindexed_knowledge_and_compute_token_cannot_bypass_bridge_scope(bridge):
    _, client, factory, _, token, _ = bridge
    conversation_id = create(client)
    rejected = client.get(
        PREFIX + "/status", headers={"Authorization": "Bearer " + token, "X-Fund-User-Id": "1"}
    )
    assert rejected.status_code == 401
    with factory.begin() as db:
        db.scalar(select(FAQ)).indexed_version = None
    assert client.get(PREFIX + "/status", headers=headers()).json()["reason"] == "knowledge_pending"
    assert ask(client, conversation_id).status_code == 503
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 0


def test_misconfigured_other_private_kb_never_receives_shadow_membership(bridge):
    app, client, factory, _, _, data = bridge
    other_id = data.kb()
    data.faq(other_id)
    app.state.settings.fund_assistant_kb_id = other_id
    assert client.get(PREFIX + "/status", headers=headers()).json()["reason"] == "knowledge_pending"
    response = client.post(PREFIX + "/conversations", json={}, headers=headers())
    assert response.status_code == 503
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(FundSubject)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeMembership)
                .where(KnowledgeMembership.kb_id == other_id)
            )
            == 1
        )  # Only the original QA owner.


def test_recent_history_stays_below_proxy_byte_budget(bridge):
    _, client, factory, _, _, _ = bridge
    conversation_id = create(client)
    with factory.begin() as db:
        conversation = db.get(Conversation, UUID(conversation_id))
        for index in range(60):
            db.add(
                Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content="规" * 8192,
                    status="complete",
                    citations=[],
                    request_id="history-budget-test",
                    created_at=datetime.now(UTC) + timedelta(microseconds=index),
                )
            )
    result = client.get(PREFIX + f"/conversations/{conversation_id}", headers=headers())
    assert result.status_code == 200
    assert 2 <= len(result.json()["messages"]) <= 50
    assert len(json.dumps(result.json(), ensure_ascii=False).encode("utf-8")) < 256 * 1024


def test_new_bridge_uses_existing_global_two_slot_bound(bridge):
    app, client, _, _, _, _ = bridge
    app.state.fund_assistant_rag = ScriptedRAG(events=[], hold=True)
    for subject in ("1", "2"):
        assert ask(client, create(client, subject), subject=subject).status_code == 202
    response = ask(client, create(client, "3"), subject="3")
    assert response.status_code == 429
    assert client.get(PREFIX + "/status", headers=headers()).json()["reason"] == "busy"


def test_revoked_service_key_cannot_persist_an_answer(bridge):
    app, client, factory, _, _, _ = bridge

    def revoke(_):
        app.state.settings.fund_assistant_service_key = None

    rag = ScriptedRAG(before_event=revoke)
    app.state.fund_assistant_rag = rag
    conversation_id = create(client)
    assert ask(client, conversation_id).status_code == 202
    assert rag.closed.wait(2)
    for _ in range(100):
        with factory() as db:
            message = db.scalar(select(Message).where(Message.role == "assistant"))
            if message.status != "generating":
                assert message.status == "cancelled" and message.content == ""
                assert db.scalar(select(func.count()).select_from(AuthSession)) == 0
                break
        time.sleep(0.02)
    else:
        pytest.fail("revoked generation was not settled")
    assert (
        client.get(PREFIX + f"/conversations/{conversation_id}", headers=headers()).status_code
        == 404
    )
    assert client.get("/health/ready").status_code == 200


def test_expired_internal_session_revokes_generation_without_exposing_partial_text(bridge):
    app, client, factory, _, _, _ = bridge

    def revoke(_):
        with factory.begin() as db:
            db.scalar(select(AuthSession)).expires_at = datetime.now(UTC) - timedelta(seconds=1)

    app.state.fund_assistant_rag = ScriptedRAG(before_event=revoke)
    conversation_id = create(client)
    assert ask(client, conversation_id).status_code == 202
    result = finished(client, conversation_id)
    assert result["status"] == "cancelled"
    assert result["messages"][-1]["content"] == ""


def test_existing_compute_protocol_updates_presence_and_accepts_bridge_scope(bridge):
    app, client, factory, worker_id, worker_token, _ = bridge
    provider = app.state.chat_rag.provider
    observed = []

    class QueueRAG:
        async def stream_answer(self, actor, kb_ids, question, history):
            observed.append((actor, kb_ids, generation_scope.get()))
            text = ""
            async for delta in provider.stream(
                [
                    LLMMessage(role="system", content=service.READ_ONLY_INSTRUCTION),
                    LLMMessage(role="user", content=question),
                ],
                max_tokens=512,
                temperature=0,
            ):
                text += delta.text
            yield AnswerEvent(type="delta", payload={"text": text})
            for event in reply()[1:]:
                yield event

    app.state.fund_assistant_rag = QueueRAG()
    with factory.begin() as db:
        db.get(ComputeWorker, worker_id).last_seen_at = None
    machine_headers = {"Authorization": "Bearer " + worker_token}
    assert (
        client.post("/internal/compute/claim", json={}, headers=machine_headers).status_code == 200
    )
    assert client.get(PREFIX + "/status", headers=headers()).json()["available"]
    conversation_id = create(client)
    assert ask(client, conversation_id).status_code == 202
    job = None
    for _ in range(100):
        job = client.post("/internal/compute/claim", json={}, headers=machine_headers).json()["job"]
        if job:
            break
        time.sleep(0.02)
    assert job is not None
    response = client.post(
        f"/internal/compute/{job['job_id']}/result",
        headers=machine_headers,
        json={
            "lease_token": job["lease_token"],
            "result": {
                "model_id": MODEL,
                "text": "排队回答成功",
                "finish_reason": "stop",
                "usage": None,
            },
        },
    )
    assert response.status_code == 204, response.text
    result = finished(client, conversation_id)
    assert result["status"] == "completed"
    assert result["messages"][-1]["content"] == "排队回答成功"
    actor, kb_ids, scope = observed[0]
    assert kb_ids == [app.state.settings.fund_assistant_kb_id]
    assert scope.actor_id == actor.user_id
    assert scope.conversation_id == UUID(conversation_id)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 0


def test_normal_qa_user_still_signs_in_and_cannot_read_shadow_conversation(bridge):
    _, client, _, _, _, _ = bridge
    conversation_id = create(client)
    _, normal_headers = sign_in(client)
    result = client.get(f"/api/v1/conversations/{conversation_id}", headers=normal_headers)
    assert result.status_code == 404
    assert client.get("/api/v1/conversations", headers=normal_headers).json()["items"] == []
