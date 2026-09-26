from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.core.models import AuditEvent
from app.core.security import AuthError
from app.modules.auth.models import User
from app.modules.chat import service as chat
from app.modules.chat.models import Conversation, Message
from app.modules.handoff import service
from app.modules.handoff.models import Handoff
from tests.chat.data_helpers import NOW, ChatData


@pytest.fixture
def data(migrated_engine):
    return ChatData(sessionmaker(migrated_engine, expire_on_commit=False))


def call(data, name, actor, identifier):
    with data.factory() as db:
        result = getattr(service, name)(db, actor, identifier, "test-handoff", NOW)
        db.commit()
        return result


def request(data, conversation):
    return call(data, "request_handoff", data.actor, conversation.id)[0]


def audit_count(data, action, identifier):
    with data.factory() as db:
        return db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == action, AuditEvent.target_id == str(identifier))
        )


def test_request_claim_close_single_state_and_idempotent_audit(data):
    conv = data.conversation()
    pending = data.reserve(conv)
    handoff, created = call(data, "request_handoff", data.actor, conv.id)
    assert created and handoff.state == "queued"
    repeated, created = call(data, "request_handoff", data.actor, conv.id)
    assert not created and repeated == handoff
    with data.factory() as db:
        assert db.get(Conversation, conv.id).generation_token is None
        assert db.get(Message, pending.assistant_message_id).status == "cancelled"
    assert not data.finish(pending)
    agent = data.person("agent")
    claimed = call(data, "claim_handoff", agent, handoff.id)
    assert claimed.state == "human" and claimed.assigned_agent_id == agent.user_id
    with pytest.raises(AuthError) as error:
        call(data, "claim_handoff", agent, handoff.id)
    assert error.value.status == 409
    assert call(data, "request_handoff", data.actor, conv.id)[0].state == "human"
    closed = call(data, "close_handoff", agent, handoff.id)
    assert closed.state == "closed" and closed.assigned_agent_id == agent.user_id
    assert call(data, "close_handoff", agent, handoff.id) == closed
    with pytest.raises(AuthError):
        call(data, "request_handoff", data.actor, conv.id)
    for action in ("request", "claim", "close"):
        assert audit_count(data, f"handoff.{action}", handoff.id) == 1


def test_two_independent_connections_claim_exactly_one_winner(data):
    conv = data.conversation()
    handoff = request(data, conv)
    agents = [data.person("agent"), data.person("agent")]
    barrier = Barrier(2)

    def race(actor):
        with data.factory() as db:
            backend_pid = db.scalar(select(func.pg_backend_pid()))
            barrier.wait(timeout=5)
            try:
                result = service.claim_handoff(db, actor, handoff.id, "race", NOW)
                db.commit()
                return actor, result.state, backend_pid
            except AuthError as error:
                db.rollback()
                return actor, error.status, backend_pid

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(race, agents))
    assert len({item[2] for item in results}) == 2
    assert sorted(str(item[1]) for item in results) == ["409", "human"]
    winner = next(item[0] for item in results if item[1] == "human")
    loser = next(item[0] for item in results if item[1] == 409)
    with data.factory() as db:
        assert db.get(Conversation, conv.id).assigned_agent_id == winner.user_id
        assert db.get(Handoff, handoff.id).claimed_by_id == winner.user_id
        with pytest.raises(AuthError) as error:
            chat.list_messages(db, loser, conv.id)
        assert error.value.status == 404
    assert audit_count(data, "handoff.claim", handoff.id) == 1


def test_parallel_duplicate_request_has_one_record_and_audit(data):
    conv = data.conversation()
    barrier = Barrier(2)

    def race(_):
        barrier.wait(timeout=5)
        return call(data, "request_handoff", data.actor, conv.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(race, range(2)))
    assert sorted(result[1] for result in results) == [False, True]
    assert results[0][0].id == results[1][0].id
    assert audit_count(data, "handoff.request", results[0][0].id) == 1


@pytest.mark.parametrize("role", ["user", "agent", "admin"])
def test_any_active_role_can_request_own_conversation(data, role):
    actor = data.person(role)
    conv = data.conversation(actor)
    assert call(data, "request_handoff", actor, conv.id)[1]


def test_queue_is_minimal_and_full_history_requires_assignment(data):
    conv = data.conversation()
    handoff = request(data, conv)
    agent = data.person("agent")
    with data.factory() as db:
        queue = service.list_queue(db, agent)
        item = next(item for item in queue.items if item.id == handoff.id)
        assert set(item.model_dump()) == {"id", "conversation_id", "requested_at", "state"}
        with pytest.raises(AuthError) as error:
            service.get_handoff(db, agent, handoff.id)
        assert error.value.status == 404
        with pytest.raises(AuthError):
            service.list_queue(db, data.actor)
    call(data, "claim_handoff", agent, handoff.id)
    with data.factory() as db:
        assert service.get_handoff(db, agent, handoff.id).state == "human"
        assert handoff.id not in [item.id for item in service.list_queue(db, agent).items]


@pytest.mark.parametrize("change", ["inactive", "role"])
def test_stale_actor_cannot_claim_or_see_queue(data, change):
    handoff = request(data, data.conversation())
    agent = data.person("agent")
    with data.factory() as db:
        user = db.get(User, agent.user_id)
        if change == "inactive":
            user.is_active = False
        else:
            user.role = "user"
        db.commit()
    with pytest.raises(AuthError) as error:
        call(data, "claim_handoff", agent, handoff.id)
    assert error.value.status == 403
    with data.factory() as db, pytest.raises(AuthError):
        service.list_queue(db, agent)


def test_foreign_admin_cannot_request_user_cannot_claim_or_close(data):
    conv = data.conversation()
    admin = data.person("admin")
    with pytest.raises(AuthError):
        call(data, "request_handoff", admin, conv.id)
    handoff = request(data, conv)
    for actor in (admin, data.actor):
        with pytest.raises(AuthError):
            call(data, "claim_handoff", actor, handoff.id)
    with pytest.raises(AuthError):
        call(data, "close_handoff", admin, handoff.id)
    call(data, "claim_handoff", data.person("agent"), handoff.id)
    with pytest.raises(AuthError):
        call(data, "close_handoff", data.actor, handoff.id)
    assert call(data, "close_handoff", admin, handoff.id).state == "closed"


def test_deleted_conversation_is_not_visible_in_queue_or_actions(data):
    conv = data.conversation()
    handoff = request(data, conv)
    agent = data.person("agent")
    with data.factory() as db:
        db.get(Conversation, conv.id).deleted_at = datetime.now(UTC)
        db.commit()
    with data.factory() as db:
        assert handoff.id not in [item.id for item in service.list_queue(db, agent).items]
    for name, actor, identifier in (
        ("request_handoff", data.actor, conv.id),
        ("claim_handoff", agent, handoff.id),
        ("close_handoff", data.person("admin"), handoff.id),
    ):
        with pytest.raises(AuthError) as error:
            call(data, name, actor, identifier)
        assert error.value.status == 404


@pytest.mark.parametrize("change", ["inactive", "role"])
def test_identity_changed_before_user_lock_is_rechecked(data, monkeypatch, change):
    from threading import Event

    conv = data.conversation()
    handoff = request(data, conv)
    agent = data.person("agent")
    entered, resume = Event(), Event()
    original = chat._current_user

    def paused(db, current_actor, *, lock=False):
        if lock and not entered.is_set():
            entered.set()
            assert resume.wait(5)
        return original(db, current_actor, lock=lock)

    monkeypatch.setattr(chat, "_current_user", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(call, data, "claim_handoff", agent, handoff.id)
        assert entered.wait(5)
        with data.factory() as db:
            user = db.get(User, agent.user_id)
            if change == "inactive":
                user.is_active = False
            else:
                user.role = "user"
            db.commit()
        resume.set()
        with pytest.raises(AuthError) as error:
            future.result(timeout=5)
        assert error.value.status == 403
    with data.factory() as db:
        assert db.get(Conversation, conv.id).mode == "queued"
        assert db.get(Handoff, handoff.id).claimed_by_id is None


def test_handoff_service_never_commits_callers_transaction(data):
    conv = data.conversation()
    with data.factory() as db:
        result, _ = service.request_handoff(db, data.actor, conv.id, "rollback", NOW)
        identifier = result.id
        db.rollback()
    with data.factory() as db:
        assert db.get(Handoff, identifier) is None
        assert db.get(Conversation, conv.id).mode == "bot"
    assert audit_count(data, "handoff.request", identifier) == 0


@pytest.mark.parametrize("role", ["user", "agent"])
def test_close_hides_another_users_handoff_existence(data, role):
    from uuid import uuid4

    handoff = request(data, data.conversation())
    assigned = data.person("agent")
    call(data, "claim_handoff", assigned, handoff.id)
    stranger = data.person(role)
    for identifier in (handoff.id, uuid4()):
        with pytest.raises(AuthError) as error:
            call(data, "close_handoff", stranger, identifier)
        assert error.value.status == 404
    assert audit_count(data, "handoff.close", handoff.id) == 0
    with data.factory() as db:
        assert service.get_handoff(db, assigned, handoff.id).state == "human"


@pytest.mark.parametrize("role", ["user", "admin"])
def test_nonagent_claim_rejection_does_not_depend_on_handoff_existence(data, role):
    from uuid import uuid4

    handoff = request(data, data.conversation())
    actor = data.person(role)
    for identifier in (handoff.id, uuid4()):
        with pytest.raises(AuthError) as error:
            call(data, "claim_handoff", actor, identifier)
        assert error.value.status == 403
    assert audit_count(data, "handoff.claim", handoff.id) == 0


def test_owner_can_view_human_handoff_but_cannot_close_it(data):
    handoff = request(data, data.conversation())
    call(data, "claim_handoff", data.person("agent"), handoff.id)
    with data.factory() as db:
        assert service.get_handoff(db, data.actor, handoff.id).state == "human"
    with pytest.raises(AuthError) as error:
        call(data, "close_handoff", data.actor, handoff.id)
    assert error.value.status == 403
