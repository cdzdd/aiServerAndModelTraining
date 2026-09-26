from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.core.security import AuthError
from app.modules.auth.models import User
from app.modules.chat.models import Conversation, GenerationUsage, Message
from tests.chat import data_helpers

chat_data = data_helpers.chat_data
NOW = data_helpers.NOW


def test_duplicate_and_conversation_conflict_do_not_spend_another_request(chat_data):
    from app.modules.chat.service import DuplicateMessage

    data = chat_data
    conversation = data.conversation()
    key = uuid4()
    first = data.reserve(conversation, key=key)
    with pytest.raises(DuplicateMessage) as error:
        data.reserve(conversation, key=key)
    assert error.value.user_message_id == first.user_message_id
    assert error.value.assistant_message_id == first.assistant_message_id
    with pytest.raises(AuthError) as error:
        data.reserve(conversation)
    assert error.value.code == "GENERATION_IN_PROGRESS"
    with data.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(GenerationUsage)
                .where(GenerationUsage.conversation_id == conversation.id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == conversation.id)
            )
            == 2
        )


def test_minute_window_excludes_exactly_sixty_seconds_ago_without_refunding_failure(chat_data):
    data = chat_data
    conversation = data.conversation()
    first = data.reserve(conversation, requests_per_minute=1)
    data.finish(first, status="failed")
    with pytest.raises(AuthError) as error:
        data.reserve(
            conversation, now=NOW + timedelta(seconds=59, milliseconds=999), requests_per_minute=1
        )
    assert error.value.status == 429
    second = data.reserve(conversation, now=NOW + timedelta(seconds=60), requests_per_minute=1)
    data.finish(second, status="cancelled")
    with data.factory() as db:
        rows = db.scalars(
            select(GenerationUsage)
            .where(GenerationUsage.conversation_id == conversation.id)
            .order_by(GenerationUsage.accepted_at)
        ).all()
        assert [row.outcome for row in rows] == ["failed", "cancelled"]
        assert all(row.total_tokens is None for row in rows)


def test_shanghai_day_limit_resets_at_sixteen_utc_not_utc_midnight(chat_data):
    data = chat_data
    conversation = data.conversation()
    before = NOW.replace(hour=15, minute=59, second=59)
    first = data.reserve(conversation, now=before, requests_per_day=1)
    data.finish(first)
    with pytest.raises(AuthError):
        data.reserve(conversation, now=before + timedelta(milliseconds=500), requests_per_day=1)
    after = data.reserve(conversation, now=before + timedelta(seconds=1), requests_per_day=1)
    assert after.accepted_at.hour == 16


def test_true_provider_usage_is_stored_and_unknown_fields_remain_null(chat_data):
    data = chat_data
    first = data.reserve(data.conversation())
    data.finish(
        first,
        done={
            "answer_status": "no_answer",
            "evidence_level": "none",
            "intent": "knowledge",
            "usage": {"prompt_tokens": 18, "completion_tokens": None, "total_tokens": None},
        },
    )
    with data.factory() as db:
        usage = db.scalar(
            select(GenerationUsage).where(GenerationUsage.user_message_id == first.user_message_id)
        )
        assert usage.prompt_tokens == 18
        assert usage.completion_tokens is usage.total_tokens is None


def test_stale_finish_cannot_overwrite_new_generation_or_clear_its_token(chat_data):
    data = chat_data
    conversation = data.conversation()
    old = data.reserve(conversation)
    assert data.finish(old, status="failed") is True
    new = data.reserve(conversation)
    assert data.finish(old, content="迟到的回答") is False
    with data.factory() as db:
        assert db.get(Conversation, conversation.id).generation_token == new.token
        assert db.get(Message, old.assistant_message_id).status == "failed"
        assert db.get(Message, new.assistant_message_id).status == "generating"


@pytest.mark.parametrize("change", [{"is_active": False}, {"role": "admin"}])
def test_finish_rechecks_current_identity_before_complete(chat_data, change):
    data = chat_data
    reservation = data.reserve(data.conversation())
    with data.factory() as db:
        db.execute(update(User).where(User.id == data.actor.user_id).values(**change))
        db.commit()
    assert data.finish(reservation, content="不得完成") is False
    with data.factory() as db:
        assert db.get(Message, reservation.assistant_message_id).status == "cancelled"
        assert db.get(Conversation, reservation.conversation_id).generation_token is None


def test_restart_recovery_finishes_orphans_and_retains_quota(chat_data):
    from app.modules.chat.service import recover_generations

    data = chat_data
    conversation = data.conversation()
    reservation = data.reserve(conversation, requests_per_day=1)
    assert recover_generations(data.factory, NOW) == 1
    assert recover_generations(data.factory, NOW) == 0
    with data.factory() as db:
        message = db.get(Message, reservation.assistant_message_id)
        assert message.status == "failed"
        assert message.error_code == "PROCESS_RESTARTED"
        assert db.get(Conversation, conversation.id).generation_token is None
        assert (
            db.scalar(
                select(GenerationUsage).where(GenerationUsage.conversation_id == conversation.id)
            ).outcome
            == "failed"
        )
    with pytest.raises(AuthError) as error:
        data.reserve(conversation, requests_per_day=1)
    assert error.value.status == 429


def test_two_connections_racing_for_last_user_quota_accept_only_one(migrated_engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.orm import sessionmaker

    data = data_helpers.ChatData(sessionmaker(bind=migrated_engine, expire_on_commit=False))
    conversations = [data.conversation(), data.conversation()]
    barrier = Barrier(2)

    def reserve(conversation):
        barrier.wait(timeout=5)
        try:
            return data.reserve(conversation, requests_per_day=1)
        except AuthError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, conversations))
    assert sum(result == 429 for result in results) == 1
    with data.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(GenerationUsage)
                .where(GenerationUsage.user_id == data.actor.user_id)
            )
            == 1
        )


@pytest.mark.parametrize(
    "count,step,limits",
    [
        (10, timedelta(0), {}),
        (60, timedelta(seconds=61), {}),
    ],
)
def test_default_request_boundaries_accept_last_then_reject_next(chat_data, count, step, limits):
    data = chat_data
    conversation = data.conversation()
    for index in range(count):
        reservation = data.reserve(conversation, now=NOW + step * index, **limits)
        data.finish(reservation)
    with pytest.raises(AuthError) as error:
        data.reserve(conversation, now=NOW + step * count, **limits)
    assert error.value.status == 429


def test_concurrent_same_client_key_creates_one_pair_and_one_usage(migrated_engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.orm import sessionmaker

    from app.modules.chat.service import DuplicateMessage

    data = data_helpers.ChatData(sessionmaker(bind=migrated_engine, expire_on_commit=False))
    conversation, key, barrier = data.conversation(), uuid4(), Barrier(2)

    def reserve(_):
        barrier.wait(timeout=5)
        try:
            return data.reserve(conversation, key=key)
        except DuplicateMessage as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, range(2)))
    duplicate = [result for result in results if isinstance(result, DuplicateMessage)]
    assert len(duplicate) == 1
    winner = next(result for result in results if not isinstance(result, DuplicateMessage))
    assert duplicate[0].user_message_id == winner.user_message_id
    assert duplicate[0].assistant_message_id == winner.assistant_message_id
    with data.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == conversation.id)
            )
            == 2
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(GenerationUsage)
                .where(GenerationUsage.conversation_id == conversation.id)
            )
            == 1
        )


@pytest.mark.parametrize("action", ["delete", "transition", "restart"])
def test_every_terminal_path_records_original_generation_request_latency_once(chat_data, action):
    from app.core.models import AuditEvent
    from app.modules.chat.service import delete_conversation, recover_generations, transition_mode

    data = chat_data
    conversation = data.conversation()
    reservation = data.reserve(conversation)
    if action == "restart":
        recover_generations(data.factory, NOW + timedelta(seconds=2))
    else:
        with data.factory() as db:
            if action == "delete":
                delete_conversation(
                    db, data.actor, conversation.id, "deletion-request", NOW + timedelta(seconds=2)
                )
            else:
                transition_mode(
                    db,
                    data.actor,
                    conversation.id,
                    expected_mode="bot",
                    next_mode="queued",
                    assigned_agent_id=None,
                    request_id="transition-request",
                )
            db.commit()
    assert data.finish(reservation, status="cancelled") is False
    with data.factory() as db:
        message = db.get(Message, reservation.assistant_message_id)
        assert message.latency_ms is not None and message.latency_ms >= 0
        audits = db.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "generation.finish",
                AuditEvent.target_id == str(conversation.id),
            )
        ).all()
        assert len(audits) == 1
        assert audits[0].request_id == reservation.request_id
        assert audits[0].event_metadata["latency_ms"] == message.latency_ms
        assert audits[0].event_metadata["status"] == message.status


@pytest.mark.parametrize("budget", ["requests_per_minute", "requests_per_day"])
def test_reverse_timestamp_order_cannot_spend_last_quota_twice(migrated_engine, budget):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from sqlalchemy.orm import sessionmaker

    data = data_helpers.ChatData(sessionmaker(bind=migrated_engine, expire_on_commit=False))
    older, newer = data.conversation(), data.conversation()
    captured, committed = Event(), Event()

    def delayed_older():
        captured.set()
        assert committed.wait(5)
        try:
            data.reserve(older, now=NOW, **{budget: 1})
            return 201
        except AuthError as exc:
            return exc.status

    def first_committer():
        assert captured.wait(5)
        try:
            data.reserve(newer, now=NOW + timedelta(milliseconds=1), **{budget: 1})
            return 201
        finally:
            committed.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        early = pool.submit(delayed_older)
        late = pool.submit(first_committer)
        assert late.result(timeout=10) == 201
        assert early.result(timeout=10) == 429
    with data.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(GenerationUsage)
                .where(
                    GenerationUsage.user_id == data.actor.user_id,
                )
            )
            == 1
        )


def test_acceptance_clock_is_sampled_after_waiting_for_user_lock(migrated_engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from sqlalchemy import event
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    data = data_helpers.ChatData(factory)
    conversation = data.conversation()
    waiting = Event()
    current = [NOW]

    def observe_lock(connection, cursor, statement, parameters, context, executemany):
        if "FROM users" in statement and "FOR UPDATE" in statement:
            waiting.set()

    with factory() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        blocker.scalar(select(User).where(User.id == data.actor.user_id).with_for_update())
        event.listen(migrated_engine, "before_cursor_execute", observe_lock)
        try:
            future = pool.submit(data.reserve, conversation, now=lambda: current[0])
            assert waiting.wait(5)
            current[0] = NOW + timedelta(seconds=2)
            blocker.commit()
            result = future.result(timeout=10)
            assert result.accepted_at == current[0]
            with factory() as db:
                saved = db.scalar(
                    select(GenerationUsage).where(
                        GenerationUsage.user_message_id == result.user_message_id,
                    )
                )
                assert saved.accepted_at == current[0]
        finally:
            blocker.rollback()
            event.remove(migrated_engine, "before_cursor_execute", observe_lock)
