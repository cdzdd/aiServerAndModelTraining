import asyncio
from uuid import uuid4

import pytest
from chat_stream_helpers import stream_app as stream_app
from chat_stream_helpers import stream_client as stream_client

from app.core.security import AuthError


def test_runtime_rejects_third_global_request_and_second_same_conversation():
    from app.modules.chat.runtime import ChatRuntime

    runtime = ChatRuntime(max_active=2)
    first, second, third = uuid4(), uuid4(), uuid4()
    slot = runtime.reserve(first)
    with pytest.raises(AuthError) as same:
        runtime.reserve(first)
    assert same.value.status == 409
    runtime.reserve(second)
    with pytest.raises(AuthError) as full:
        runtime.reserve(third)
    assert full.value.status == 429
    runtime.release(first, uuid4())
    with pytest.raises(AuthError):
        runtime.reserve(third)
    runtime.release(first, slot)
    assert runtime.reserve(third)


def test_runtime_shutdown_cancels_and_waits_for_upstream_cleanup():
    from app.modules.chat.runtime import ChatRuntime

    async def run():
        runtime = ChatRuntime(max_active=2)
        conversation_id = uuid4()
        slot = runtime.reserve(conversation_id)
        started, closed = asyncio.Event(), asyncio.Event()

        async def generation():
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                closed.set()
                runtime.release(conversation_id, slot)

        task = asyncio.create_task(generation())
        runtime.bind(conversation_id, slot, task)
        await started.wait()
        await runtime.shutdown()
        assert task.cancelled()
        assert closed.is_set()
        assert runtime.reserve(conversation_id)

    asyncio.run(run())


def test_stream_meta_then_done_persists_messages_and_actual_usage(stream_app, stream_client):
    from chat_stream_helpers import (
        ScriptedRAG,
        assistant,
        conversation,
        parse_sse,
        reply,
        send,
        sign_in,
    )
    from sqlalchemy import select

    from app.modules.chat.models import GenerationUsage

    usage = {"prompt_tokens": 13, "completion_tokens": None, "total_tokens": None}
    stream_app.state.chat_rag = ScriptedRAG(reply(usage))
    _, headers = sign_in(stream_client)
    cid = conversation(stream_client, stream_app, headers)
    response = send(stream_client, cid, headers)
    assert response.status_code == 200
    events = parse_sse(response.text)
    assert [kind for kind, _ in events] == ["meta", "delta", "citations", "done"]
    saved = assistant(stream_app, cid)
    assert str(saved.id) == events[0][1]["assistant_message_id"]
    assert str(saved.in_reply_to_id) == events[0][1]["user_message_id"]
    assert saved.status == "complete"
    assert saved.content == "当前资料中没有依据。"
    with stream_app.state.session_factory() as db:
        record = db.scalar(
            select(GenerationUsage).where(GenerationUsage.assistant_message_id == saved.id)
        )
        assert record.prompt_tokens == 13
        assert record.completion_tokens is None
        assert record.total_tokens is None
        assert record.outcome == "complete"


@pytest.mark.parametrize("events", [[], [RuntimeError("PRIVATE-DETAIL")]])
def test_incomplete_or_failed_rag_never_emits_done(stream_app, stream_client, events):
    from chat_stream_helpers import ScriptedRAG, assistant, conversation, parse_sse, send, sign_in

    stream_app.state.chat_rag = ScriptedRAG(events)
    _, headers = sign_in(stream_client)
    cid = conversation(stream_client, stream_app, headers)
    response = send(stream_client, cid, headers)
    kinds = [kind for kind, _ in parse_sse(response.text)]
    assert kinds == ["meta", "error"]
    assert "PRIVATE-DETAIL" not in response.text
    assert assistant(stream_app, cid).status == "failed"
    assert stream_app.state.chat_rag.closed.is_set()


def test_duplicate_request_does_not_reserve_another_usage(stream_app, stream_client):
    from chat_stream_helpers import conversation, send, sign_in

    _, headers = sign_in(stream_client)
    cid = conversation(stream_client, stream_app, headers)
    key = uuid4()
    original = send(stream_client, cid, headers, key)
    duplicate = send(stream_client, cid, headers, key)
    assert original.status_code == 200
    assert duplicate.status_code == 409
    error = duplicate.json()["error"]
    assert error["code"] == "DUPLICATE_MESSAGE"
    assert error["details"][0]["user_message_id"]
    assert error["details"][0]["assistant_message_id"]
    assert stream_app.state.chat_rag.calls == 1


@pytest.mark.parametrize("change", ["inactive", "role", "logout", "mode", "delete"])
def test_fresh_authority_check_stops_late_events(stream_app, stream_client, change):
    from datetime import UTC, datetime
    from uuid import UUID

    from chat_stream_helpers import ScriptedRAG, assistant, conversation, parse_sse, send, sign_in
    from sqlalchemy import delete

    from app.modules.auth.models import AuthSession, User
    from app.modules.chat.models import Conversation

    user, headers = sign_in(stream_client)
    cid = conversation(stream_client, stream_app, headers)

    def revoke(event):
        with stream_app.state.session_factory() as db:
            account = db.get(User, UUID(user["id"]))
            conv = db.get(Conversation, UUID(cid))
            if change == "inactive":
                account.is_active = False
            elif change == "role":
                account.role = "agent"
            elif change == "logout":
                db.execute(delete(AuthSession).where(AuthSession.user_id == account.id))
            elif change == "mode":
                conv.mode = "queued"
            else:
                conv.deleted_at = datetime.now(UTC)
            db.commit()

    stream_app.state.chat_rag = ScriptedRAG(before_event=revoke)
    response = send(stream_client, cid, headers)
    assert [kind for kind, _ in parse_sse(response.text)] == ["meta", "error"]
    assert "当前资料中没有依据" not in response.text
    assert assistant(stream_app, cid).status == "cancelled"


def test_recovery_failure_disables_chat_writes(stream_app, stream_client):
    from chat_stream_helpers import sign_in

    _, headers = sign_in(stream_client)
    stream_app.state.chat_ready = False
    response = stream_client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"kb_ids": [str(stream_app.state.test_kb_id)]},
    )
    assert response.status_code == 503


@pytest.mark.parametrize("role", ["admin", "agent"])
def test_privileged_roles_can_generate_in_their_own_conversation(stream_app, stream_client, role):
    from uuid import UUID

    from chat_stream_helpers import conversation, send, sign_in

    from app.modules.auth.models import User

    user, headers = sign_in(stream_client)
    with stream_app.state.session_factory() as db:
        db.get(User, UUID(user["id"])).role = role
        db.commit()
    cid = conversation(stream_client, stream_app, headers)
    response = send(stream_client, cid, headers)
    assert response.status_code == 200
    assert "event: done" in response.text


def test_complete_commit_failure_never_sends_done(stream_app, stream_client, monkeypatch):
    from chat_stream_helpers import assistant, conversation, parse_sse, send, sign_in

    from app.modules.chat import service

    _, headers = sign_in(stream_client)
    cid = conversation(stream_client, stream_app, headers)
    original = service.finish_generation

    def fail_completion(*args, **kwargs):
        if kwargs["status"] == "complete":
            raise RuntimeError("private database failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "finish_generation", fail_completion)
    response = send(stream_client, cid, headers)
    assert [kind for kind, _ in parse_sse(response.text)] == ["meta", "delta", "citations", "error"]
    assert "private database failure" not in response.text
    assert assistant(stream_app, cid).status == "failed"


def test_response_cleanup_releases_slot_even_when_iterator_close_fails():
    from types import SimpleNamespace

    from app.modules.chat.runtime import ChatRuntime
    from app.modules.chat.streaming import ChatStreamingResponse

    async def run():
        runtime = ChatRuntime(1)
        cid = uuid4()
        slot = runtime.reserve(cid)
        closed = False

        class Iterator:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

            async def aclose(self):
                raise RuntimeError("upstream close failed")

        class Generation:
            reservation = SimpleNamespace(conversation_id=cid)

            def events(self):
                return Iterator()

            async def close(self):
                nonlocal closed
                closed = True

        async def receive():
            await asyncio.Event().wait()

        async def send(message):
            pass

        response = ChatStreamingResponse(Generation(), runtime, slot)
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        assert closed
        assert runtime.reserve(cid)

    asyncio.run(run())


def test_cancelled_cited_delta_retains_source_binding_for_later_permission_revocation(
    migrated_engine,
):
    import json
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from sqlalchemy import delete
    from sqlalchemy.orm import sessionmaker

    from app.core.security import SESSION_COOKIE, token_hash
    from app.modules.auth.models import AuthSession
    from app.modules.chat.models import Message
    from app.modules.chat.service import list_messages
    from app.modules.chat.streaming import GenerationStream
    from app.modules.knowledge.models import KnowledgeMembership
    from app.modules.providers.schemas import LLMDelta
    from app.modules.rag.service import RAGService
    from app.modules.retrieval.service import RetrievalService
    from tests.chat.data_helpers import ChatData
    from tests.retrieval.search_helpers import FixedEmbedder

    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    data = ChatData(factory)
    kb = data.kb()
    quote = "测试私有资料：图书馆九点开放。"
    data.document(kb, text=quote)
    conv = data.conversation(kb_ids=[kb])
    now = datetime.now(UTC)
    reservation = data.reserve(conv, now=now)
    cookie = "test-cited-stream-" + uuid4().hex
    with factory() as db:
        db.add(
            AuthSession(
                user_id=data.actor.user_id,
                token_hash=token_hash(cookie),
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        db.commit()

    class Provider:
        async def stream(self, messages, *, max_tokens, temperature):
            yield LLMDelta(
                text=json.dumps(
                    {"status": "answered", "selections": [{"index": 1, "quote": quote}]}
                )
            )
            yield LLMDelta(finish_reason="stop")

    retrieval = RetrievalService(factory, FixedEmbedder())
    state = SimpleNamespace(
        session_factory=factory,
        chat_clock=lambda: datetime.now(UTC),
        auth_clock=lambda: datetime.now(UTC),
        chat_rag=RAGService(retrieval.search, retrieval.validate_hits, Provider()),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state), cookies={SESSION_COOKIE: cookie})

    async def run():
        generation = GenerationStream(request, reservation)
        events = generation.events()
        assert (await anext(events)).startswith("event: meta\n")
        first_text = await anext(events)
        assert first_text.startswith("event: delta\n") and quote in first_text
        await events.aclose()
        await generation.close()

    asyncio.run(run())
    with migrated_engine.begin() as db:
        db.execute(delete(KnowledgeMembership).where(KnowledgeMembership.kb_id == kb))
    with factory() as db:
        saved = db.get(Message, reservation.assistant_message_id)
        assert saved.status == "cancelled"
        assert quote in saved.content
        projected = list_messages(db, data.actor, conv.id)["items"][1]
        assert projected.evidence_hidden is True
        assert quote not in projected.content
        assert projected.citations == []
        assert saved.citations[0]["quote"] == quote


def test_rag_text_without_citations_is_neither_shown_nor_persisted(stream_app, stream_client):
    from chat_stream_helpers import ScriptedRAG, assistant, conversation, parse_sse, send, sign_in

    from app.modules.rag.schemas import AnswerEvent

    stream_app.state.chat_rag = ScriptedRAG(
        [
            AnswerEvent(type="delta", payload={"text": "尚未绑定来源的原文"}),
            RuntimeError("failed before citations"),
        ]
    )
    _, headers = sign_in(stream_client)
    cid = conversation(stream_client, stream_app, headers)
    response = send(stream_client, cid, headers)
    assert [kind for kind, _ in parse_sse(response.text)] == ["meta", "error"]
    assert "尚未绑定来源的原文" not in response.text
    assert assistant(stream_app, cid).content == ""
