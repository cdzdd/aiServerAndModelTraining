from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.orm import Session

from app.core.models import AuditEvent

_SENSITIVE_KEY_PARTS = (
    "password",
    "token",
    "apikey",
    "authorization",
    "cookie",
    "secret",
    "credential",
    "databaseurl",
    "content",
    "message",
    "history",
    "prompt",
    "transcript",
    "chat",
    "question",
    "answer",
    "body",
)


def _redact(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(
                part in "".join(c for c in key.lower() if c.isalnum())
                for part in _SENSITIVE_KEY_PARTS
            )
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def record_audit(
    db: Session,
    *,
    actor_id: UUID | None,
    action: str,
    target_type: str,
    target_id: str | None,
    outcome: str,
    request_id: str,
    metadata: dict[str, JsonValue],
) -> AuditEvent:
    """Flush in the caller's transaction; metadata should contain only IDs, counts and outcomes.

    Common credential and chat-content keys are recursively redacted as a second safeguard.
    This function never commits the business transaction or writes raw chat to application logs.
    """
    event = AuditEvent(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        request_id=request_id,
        event_metadata=_redact(metadata),
    )
    db.add(event)
    db.flush()
    return event
