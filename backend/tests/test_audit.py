from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session


def test_audit_is_persisted_with_actor_target_request_and_utc_time(request):
    from app.core.audit import record_audit
    from app.core.models import AuditEvent

    migrated_engine = request.getfixturevalue("migrated_engine")

    actor_id, target_id = uuid4(), uuid4()
    request_id = str(uuid4())
    started_at = datetime.now(UTC)
    with Session(migrated_engine) as db, db.begin():
        event = record_audit(
            db,
            actor_id=actor_id,
            action="document.create",
            target_type="document",
            target_id=str(target_id),
            outcome="success",
            request_id=request_id,
            metadata={"count": 1},
        )
        event_id = event.id
        assert isinstance(event_id, UUID)
    with Session(migrated_engine) as db:
        saved = db.scalar(select(AuditEvent).where(AuditEvent.id == event_id))
        assert saved is not None
        assert saved.actor_id == actor_id
        assert saved.action == "document.create"
        assert saved.target_type == "document"
        assert saved.target_id == str(target_id)
        assert saved.outcome == "success"
        assert saved.request_id == request_id
        assert saved.created_at.utcoffset().total_seconds() == 0
        assert started_at <= saved.created_at <= datetime.now(UTC)
        assert saved.event_metadata == {"count": 1}


def test_audit_redacts_nested_credentials_and_chat_content(request):
    from app.core.audit import record_audit
    from app.core.models import AuditEvent

    migrated_engine = request.getfixturevalue("migrated_engine")

    supplied = {
        "operation": "login",
        "password": "raw-password",
        "nested": [{"API-Key": "raw-key", "Authorization": "Bearer raw-token", "count": 2}],
        "refreshToken": "raw-token",
        "Cookie": "raw-cookie",
        "client_secret": "raw-secret",
        "connection": {
            "DATABASE_URL": "postgresql://test:private-dsn@localhost/test",
            "TEST_DATABASE_URL": "private-test-dsn",
        },
        "messages": [{"role": "user", "content": "private-chat"}],
    }
    with Session(migrated_engine) as db, db.begin():
        event = record_audit(
            db,
            actor_id=None,
            action="auth.login",
            target_type="session",
            target_id=None,
            outcome="failure",
            request_id=str(uuid4()),
            metadata=supplied,
        )
        event_id = event.id
    with Session(migrated_engine) as db:
        saved = db.get(AuditEvent, event_id)
        assert saved.actor_id is None
        assert saved.event_metadata == {
            "operation": "login",
            "password": "[REDACTED]",
            "nested": [{"API-Key": "[REDACTED]", "Authorization": "[REDACTED]", "count": 2}],
            "refreshToken": "[REDACTED]",
            "Cookie": "[REDACTED]",
            "client_secret": "[REDACTED]",
            "connection": {"DATABASE_URL": "[REDACTED]", "TEST_DATABASE_URL": "[REDACTED]"},
            "messages": "[REDACTED]",
        }
    assert supplied["password"] == "raw-password"


def test_audit_does_not_commit_the_callers_transaction(request):
    from app.core.audit import record_audit
    from app.core.models import AuditEvent

    migrated_engine = request.getfixturevalue("migrated_engine")

    with Session(migrated_engine) as db:
        event = record_audit(
            db,
            actor_id=None,
            action="test.rollback",
            target_type="test",
            target_id=None,
            outcome="failure",
            request_id=str(uuid4()),
            metadata={},
        )
        event_id = event.id
        db.rollback()
    with Session(migrated_engine) as db:
        assert db.get(AuditEvent, event_id) is None
