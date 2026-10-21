from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class GenerationScope:
    conversation_id: UUID
    assistant_message_id: UUID
    generation_token: UUID
    actor_id: UUID
    actor_role: str
    session_hash: str
    deadline: datetime


generation_scope: ContextVar[GenerationScope | None] = ContextVar("generation_scope", default=None)


@contextmanager
def bind_scope(scope: GenerationScope):
    token = generation_scope.set(scope)
    try:
        yield
    finally:
        generation_scope.reset(token)
