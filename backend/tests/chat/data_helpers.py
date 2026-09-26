from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.modules.auth.models import User
from app.modules.auth.schemas import Actor
from tests.retrieval.search_helpers import SearchData

NOW = datetime(2026, 9, 26, 5, 0, tzinfo=UTC)


class ChatData(SearchData):
    def person(self, role="user", active=True):
        with self.factory() as db:
            user = User(
                username=uuid4().hex,
                display_name="测试",
                password_hash="unused",
                role=role,
                is_active=active,
            )
            db.add(user)
            db.commit()
            return Actor(user_id=user.id, role=role)

    def conversation(self, actor=None, kb_ids=None):
        from app.modules.chat.service import create_conversation

        actor = actor or self.actor
        kb_ids = kb_ids or [self.kb(visibility="public")]
        with self.factory() as db:
            result = create_conversation(db, actor, kb_ids, "test-request")
            db.commit()
            return result

    def reserve(self, conversation, actor=None, now=NOW, key=None, **limits):
        from app.modules.chat.service import reserve_generation

        with self.factory() as db:
            result = reserve_generation(
                db,
                actor or self.actor,
                conversation.id,
                "开放时间？",
                key or uuid4(),
                "test-request",
                now,
                **limits,
            )
            db.commit()
            return result

    def finish(self, reservation, status="complete", citations=None, content="固定回复", done=None):
        from app.modules.chat.service import finish_generation

        with self.factory() as db:
            result = finish_generation(
                db,
                reservation,
                status=status,
                content=content,
                citations=citations or [],
                done=done
                or {
                    "answer_status": "no_answer",
                    "evidence_level": "none",
                    "intent": "knowledge",
                    "usage": None,
                },
                error_code=None,
                latency_ms=8,
                now=NOW,
            )
            db.commit()
            return result


@pytest.fixture
def chat_data(migrated_engine):
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        factory = sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        yield ChatData(factory)
        transaction.rollback()
