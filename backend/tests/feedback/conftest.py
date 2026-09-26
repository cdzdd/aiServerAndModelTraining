from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.modules.auth.models import User
from app.modules.chat.models import Conversation, Message
from app.modules.knowledge.models import KnowledgeBase
from tests.auth import conftest as auth_fixtures
from tests.auth.conftest import login, register

auth_app = auth_fixtures.auth_app
client = auth_fixtures.client
user = auth_fixtures.user
signed_in = auth_fixtures.signed_in


@pytest.fixture
def reply(auth_app, signed_in):
    with auth_app.state.session_factory() as db:
        kb = KnowledgeBase(name="反馈测试", visibility="public")
        db.add(kb)
        db.flush()
        conversation = Conversation(user_id=UUID(signed_in["id"]), kb_ids=[str(kb.id)])
        db.add(conversation)
        db.flush()
        question = Message(
            conversation_id=conversation.id,
            role="user",
            author_id=conversation.user_id,
            content="测试问题",
            client_message_id=uuid4(),
            request_id="fixture",
        )
        db.add(question)
        db.flush()
        message = Message(
            conversation_id=conversation.id,
            role="assistant",
            status="complete",
            content="测试回答",
            in_reply_to_id=question.id,
            request_id="fixture",
        )
        db.add(message)
        db.commit()
        return {
            "id": str(message.id),
            "conversation_id": str(conversation.id),
            "kb_id": str(kb.id),
            "question_id": str(question.id),
        }


@pytest.fixture
def admin_reader(auth_app):
    with TestClient(auth_app) as client:
        person = register(client).json()
        with auth_app.state.session_factory() as db:
            db.execute(update(User).where(User.id == UUID(person["id"])).values(role="admin"))
            db.commit()
        assert login(client, person["username"]).status_code == 200
        yield client, person
        with auth_app.state.session_factory() as db:
            db.execute(update(User).where(User.id == UUID(person["id"])).values(role="user"))
            db.commit()
