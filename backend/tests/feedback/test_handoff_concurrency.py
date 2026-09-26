"""Real PostgreSQL serialization across handoff and feedback write transactions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import sessionmaker

from app.core.models import AuditEvent
from app.modules.chat.models import Conversation, Message
from app.modules.feedback import service as feedback_service
from app.modules.feedback.models import Feedback
from app.modules.feedback.schemas import FeedbackCreate, ResolutionInput
from app.modules.handoff import service as handoff_service
from app.modules.handoff.models import Handoff
from tests.chat.data_helpers import NOW, ChatData


def wait_for_user_lock(factory, waiting_pid, blocking_pid):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        with factory() as db:
            waiting = db.execute(
                text(
                    "SELECT wait_event_type, query, pg_blocking_pids(pid) "
                    "FROM pg_stat_activity WHERE pid = :pid"
                ),
                {"pid": waiting_pid},
            ).one()
        if waiting.wait_event_type == "Lock" and blocking_pid in waiting.pg_blocking_pids:
            statement = " ".join(waiting.query.lower().split())
            assert "from users " in statement and "for update" in statement
            return
        sleep(0.01)
    raise AssertionError("Second transaction did not block on the first transaction's User lock")


@pytest.mark.parametrize("first_operation", ["close", "resolve"])
def test_same_admin_close_and_feedback_resolution_serialize(migrated_engine, first_operation):
    factory = sessionmaker(migrated_engine, expire_on_commit=False)
    data = ChatData(factory)
    admin, agent = data.person("admin"), data.person("agent")
    conversation = data.conversation()
    reservation = data.reserve(conversation)
    assert data.finish(reservation, content="此前已完成的 AI 回答")
    with factory() as db:
        feedback, _ = feedback_service.submit_feedback(
            db,
            data.actor,
            reservation.assistant_message_id,
            FeedbackCreate(rating="down", comment="需要核实"),
            "setup-feedback",
        )
        handoff, _ = handoff_service.request_handoff(
            db, data.actor, conversation.id, "setup-request", NOW
        )
        db.commit()
    with factory() as db:
        handoff_service.claim_handoff(db, agent, handoff.id, "setup-claim", NOW)
        db.commit()

    first_has_conversation, second_started, release = Event(), Event(), Event()
    second_operation = "resolve" if first_operation == "close" else "close"
    pids, acquired_locks = {}, {"close": [], "resolve": []}

    def run(operation):
        with factory() as db:
            connection = db.connection()
            pids[operation] = db.scalar(select(func.pg_backend_pid()))

            def observe_real_lock(conn, cursor, statement, parameters, context, executemany):
                sql = " ".join(statement.lower().split())
                if "for update" not in sql:
                    return
                for table in ("users", "conversations", "handoffs", "feedback"):
                    if f"from {table} " in sql:
                        acquired_locks[operation].append(table)
                        if (
                            operation == first_operation
                            and table == "conversations"
                            and not first_has_conversation.is_set()
                        ):
                            # SQL has completed: PostgreSQL actually holds the row locks.
                            first_has_conversation.set()
                            assert release.wait(10)
                        break

            event.listen(connection, "after_cursor_execute", observe_real_lock)
            try:
                if operation == second_operation:
                    second_started.set()
                if operation == "close":
                    result = handoff_service.close_handoff(
                        db, admin, handoff.id, "concurrent-close", NOW
                    ).state
                else:
                    result = feedback_service.resolve_feedback(
                        db,
                        admin,
                        feedback.id,
                        ResolutionInput(status="resolved", resolution="已核实"),
                        "concurrent-resolve",
                    ).status
                db.commit()
                return result
            finally:
                event.remove(connection, "after_cursor_execute", observe_real_lock)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run, first_operation)
        try:
            assert first_has_conversation.wait(5)
            second = executor.submit(run, second_operation)
            assert second_started.wait(5)
            assert pids[first_operation] != pids[second_operation]
            wait_for_user_lock(factory, pids[second_operation], pids[first_operation])
            assert not second.done()
        finally:
            release.set()
        results = {first_operation: first.result(timeout=10), second_operation: second.result(10)}
    assert results == {"close": "closed", "resolve": "resolved"}
    # These are completed database SELECT FOR UPDATE operations, not mocked lock calls.
    assert acquired_locks["close"][:3] == ["users", "conversations", "handoffs"]
    assert acquired_locks["resolve"] == ["users", "conversations", "feedback"]

    with factory() as db:
        stored_conversation = db.get(Conversation, conversation.id)
        stored_handoff = db.get(Handoff, handoff.id)
        stored_feedback = db.get(Feedback, feedback.id)
        stored_message = db.get(Message, reservation.assistant_message_id)
        assert stored_conversation.mode == "closed"
        assert stored_conversation.assigned_agent_id == agent.user_id
        assert stored_handoff.closed_by_id == admin.user_id and stored_handoff.closed_at == NOW
        assert stored_feedback.status == "resolved" and stored_feedback.resolution == "已核实"
        assert stored_feedback.resolved_by == admin.user_id and stored_feedback.resolved_at
        assert (
            stored_message.status == "complete" and stored_message.content == "此前已完成的 AI 回答"
        )
        audits = db.scalars(
            select(AuditEvent).where(
                AuditEvent.request_id.in_(["concurrent-close", "concurrent-resolve"]),
                AuditEvent.target_id.in_([str(conversation.id), str(handoff.id), str(feedback.id)]),
            )
        ).all()
        assert sorted(item.action for item in audits) == [
            "conversation.transition",
            "feedback.resolve",
            "handoff.close",
        ]
        assert all(item.actor_id == admin.user_id and item.outcome == "success" for item in audits)
        assert "需要核实" not in str([item.event_metadata for item in audits])
        assert "已核实" not in str([item.event_metadata for item in audits])
