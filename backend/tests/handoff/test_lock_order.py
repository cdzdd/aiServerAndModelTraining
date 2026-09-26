from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.security import AuthError
from app.modules.chat import service as chat
from app.modules.chat.models import Conversation
from app.modules.handoff import service
from tests.chat.data_helpers import NOW
from tests.handoff.test_state_transitions import call, request
from tests.handoff.test_state_transitions import data as data


def wait_for_database_lock(data, pid):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        with data.factory() as db:
            waiting = db.scalar(
                text("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            )
        if waiting:
            return
        sleep(0.01)
    raise AssertionError("Competing transaction did not wait on a PostgreSQL lock")


@pytest.mark.parametrize("operation", ["close_reply", "request_reserve"])
def test_handoff_and_chat_writes_serialize_without_deadlock(data, monkeypatch, operation):
    conv = data.conversation()
    actor = data.actor
    identifier = conv.id
    handoff_method = "request_handoff"
    if operation == "close_reply":
        handoff = request(data, conv)
        actor = data.person("agent")
        call(data, "claim_handoff", actor, handoff.id)
        identifier = handoff.id
        handoff_method = "close_handoff"
    conv_locked, release, competitor_started = Event(), Event(), Event()
    original = chat._conversation
    pids = {}

    def pause_after_conversation_lock(db, conversation_id, *, lock=False):
        result = original(db, conversation_id, lock=lock)
        if db.info.get("handoff_writer") and lock and not conv_locked.is_set():
            conv_locked.set()
            assert release.wait(10)
        return result

    monkeypatch.setattr(chat, "_conversation", pause_after_conversation_lock)

    def run(is_handoff):
        with data.factory() as db:
            db.info["handoff_writer"] = is_handoff
            pids[is_handoff] = db.scalar(select(func.pg_backend_pid()))
            if not is_handoff:
                competitor_started.set()
            try:
                if is_handoff:
                    getattr(service, handoff_method)(db, actor, identifier, "lock-test", NOW)
                elif operation == "close_reply":
                    chat.add_text_message(db, actor, conv.id, "客服回复", uuid4(), "lock-test")
                else:
                    chat.reserve_generation(
                        db, actor, conv.id, "图书馆几点开门？", uuid4(), "lock-test", NOW
                    )
                db.commit()
                return "ok"
            except AuthError as error:
                db.rollback()
                return error.status
            except DBAPIError as error:
                db.rollback()
                return error.orig.sqlstate

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, True)
        assert conv_locked.wait(5)
        second = pool.submit(run, False)
        try:
            assert competitor_started.wait(5)
            assert pids[True] != pids[False]
            wait_for_database_lock(data, pids[False])
        finally:
            release.set()
        assert (first.result(timeout=10), second.result(timeout=10)) == ("ok", 409)
    with data.factory() as db:
        assert db.get(Conversation, conv.id).mode == (
            "closed" if operation == "close_reply" else "queued"
        )


@pytest.mark.parametrize("operation", ["request_handoff", "claim_handoff", "close_handoff"])
def test_identity_update_waits_for_handoff_transaction(data, monkeypatch, operation):
    from sqlalchemy import update

    from app.modules.auth.models import User

    conv = data.conversation()
    actor, identifier = data.actor, conv.id
    if operation != "request_handoff":
        handoff = request(data, conv)
        actor, identifier = data.person("agent"), handoff.id
        if operation == "close_handoff":
            call(data, "claim_handoff", actor, identifier)
    locked, release, update_started = Event(), Event(), Event()
    original = chat._conversation
    update_pid = []

    def paused(db, conversation_id, *, lock=False):
        result = original(db, conversation_id, lock=lock)
        if lock and not locked.is_set():
            locked.set()
            assert release.wait(10)
        return result

    monkeypatch.setattr(chat, "_conversation", paused)

    def disable():
        with data.factory() as db:
            update_pid.append(db.scalar(select(func.pg_backend_pid())))
            update_started.set()
            db.execute(update(User).where(User.id == actor.user_id).values(is_active=False))
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        changed = pool.submit(call, data, operation, actor, identifier)
        assert locked.wait(5)
        disabled = pool.submit(disable)
        try:
            assert update_started.wait(5)
            wait_for_database_lock(data, update_pid[0])
            assert not disabled.done()
        finally:
            release.set()
        changed.result(timeout=10)
        disabled.result(timeout=10)
    with data.factory() as db:
        assert not db.get(User, actor.user_id).is_active
        assert (
            db.get(Conversation, conv.id).mode
            == {"request_handoff": "queued", "claim_handoff": "human", "close_handoff": "closed"}[
                operation
            ]
        )
