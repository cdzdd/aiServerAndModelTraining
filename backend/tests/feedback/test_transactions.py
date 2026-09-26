from uuid import UUID

import pytest
from sqlalchemy import func, select, update

from app.core.models import AuditEvent
from app.core.security import AuthError
from app.modules.auth.models import User
from app.modules.auth.schemas import Actor
from app.modules.feedback import service
from app.modules.feedback.models import Feedback
from app.modules.feedback.schemas import FeedbackCreate, ResolutionInput
from tests.feedback.test_resolution import submit


def test_audit_failure_rolls_back_creation(client, reply, signed_in, auth_app, monkeypatch):
    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service, "record_audit", fail_audit)
    with auth_app.state.session_factory() as db:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            service.submit_feedback(
                db,
                Actor(user_id=UUID(signed_in["id"]), role="user"),
                UUID(reply["id"]),
                FeedbackCreate(rating="up"),
                "atomic-create",
            )
        db.rollback()
    with auth_app.state.session_factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Feedback)
                .where(Feedback.message_id == UUID(reply["id"]))
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.request_id == "atomic-create")
            )
            == 0
        )


def test_audit_failure_rolls_back_resolution(client, reply, admin_reader, auth_app, monkeypatch):
    _, admin = admin_reader
    feedback = submit(client, reply)

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service, "record_audit", fail_audit)
    with auth_app.state.session_factory() as db:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            service.resolve_feedback(
                db,
                Actor(user_id=UUID(admin["id"]), role="admin"),
                UUID(feedback["id"]),
                ResolutionInput(status="resolved", resolution="核实"),
                "atomic-resolve",
            )
        db.rollback()
    with auth_app.state.session_factory() as db:
        row = db.get(Feedback, UUID(feedback["id"]))
        assert row.status == "open" and row.resolved_at is None
        assert row.resolution == ""
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.request_id == "atomic-resolve")
            )
            == 0
        )


@pytest.mark.parametrize("change", [{"is_active": False}, {"role": "agent"}])
def test_stale_owner_identity_cannot_submit(reply, signed_in, auth_app, change):
    actor = Actor(user_id=UUID(signed_in["id"]), role="user")
    with auth_app.state.session_factory() as stale_db:
        stale_db.get(User, actor.user_id)
        with auth_app.state.engine.begin() as connection:
            connection.execute(update(User).where(User.id == actor.user_id).values(**change))
        with pytest.raises(AuthError) as error:
            service.submit_feedback(
                stale_db, actor, UUID(reply["id"]), FeedbackCreate(rating="up"), "stale-owner"
            )
        assert error.value.status == 403


def test_demoted_admin_cannot_process_feedback(client, reply, admin_reader, auth_app):
    _, admin = admin_reader
    feedback = submit(client, reply)
    actor = Actor(user_id=UUID(admin["id"]), role="admin")
    with auth_app.state.session_factory() as stale_db:
        stale_db.get(User, actor.user_id)
        with auth_app.state.engine.begin() as connection:
            connection.execute(update(User).where(User.id == actor.user_id).values(role="user"))
        with pytest.raises(AuthError) as error:
            service.resolve_feedback(
                stale_db,
                actor,
                UUID(feedback["id"]),
                ResolutionInput(status="resolved", resolution="核实"),
                "stale-admin",
            )
        assert error.value.status == 403


def test_concurrent_owner_edit_and_resolution_keep_serial_state(
    client, reply, admin_reader, auth_app
):
    from concurrent.futures import ThreadPoolExecutor

    from tests.auth.conftest import csrf

    admin, _ = admin_reader
    feedback = submit(client, reply)
    owner_headers, admin_headers = csrf(client), csrf(admin)
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(
            client.patch,
            f"/api/v1/feedback/{feedback['id']}",
            json={"comment": "并发补充"},
            headers=owner_headers,
        )
        resolver = pool.submit(
            admin.patch,
            f"/api/v1/admin/feedback/{feedback['id']}",
            json={"status": "resolved", "resolution": "核查完成"},
            headers=admin_headers,
        )
        assert owner.result(timeout=10).status_code == 200
        assert resolver.result(timeout=10).status_code == 200
    with auth_app.state.session_factory() as db:
        row = db.get(Feedback, UUID(feedback["id"]))
        assert row.comment == "并发补充"
        audits = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.target_id == feedback["id"])
            .order_by(AuditEvent.created_at)
        ).all()
        assert len(audits) == 3
        if audits[-1].action == "feedback.resolve":
            assert row.status == "resolved" and row.resolution == "核查完成"
        else:
            assert audits[-1].action == "feedback.update"
            assert row.status == "open" and row.resolved_by is None and row.resolution == ""
