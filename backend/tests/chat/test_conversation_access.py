from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select, update

from app.core.models import AuditEvent
from app.core.security import AuthError
from app.modules.auth.models import User
from app.modules.chat.models import Conversation, Message
from tests.chat import data_helpers


@pytest.mark.parametrize("content", ["", "  ", "a" * 2001, "bad\0text", "\ud800"])
def test_invalid_message_content_is_rejected(content):
    from app.modules.chat.schemas import MessageInput

    with pytest.raises(ValidationError):
        MessageInput(content=content, client_message_id=uuid4())


def test_conversation_input_cannot_expand_empty_or_duplicate_scope():
    from app.modules.chat.schemas import ConversationCreate

    for scope in [[], [uuid4()] * 2]:
        with pytest.raises(ValidationError):
            ConversationCreate(kb_ids=scope)


chat_data = data_helpers.chat_data


def test_list_detail_and_message_access_filter_before_pagination(chat_data):
    from app.modules.chat.service import get_conversation, get_message, list_conversations

    data = chat_data
    other, agent, admin = data.person(), data.person("agent"), data.person("admin")
    first = data.conversation()
    second = data.conversation(other)
    reservation = data.reserve(first)
    with data.factory() as db:
        assert list_conversations(db, data.actor)["total"] == 1
        assert list_conversations(db, other)["items"][0].id == second.id
        assert list_conversations(db, admin)["total"] == 2
        for reader in [other, agent]:
            with pytest.raises(AuthError) as error:
                get_conversation(db, reader, first.id)
            assert error.value.status == 404
            with pytest.raises(AuthError):
                get_message(db, reader, reservation.user_message_id)
        db.execute(
            update(Conversation)
            .where(Conversation.id == first.id)
            .values(assigned_agent_id=agent.user_id, mode="human")
        )
        db.commit()
    with data.factory() as db:
        assert get_message(db, agent, reservation.user_message_id).content == "开放时间？"
        assert list_conversations(db, agent)["total"] == 1


def test_create_rejects_any_invisible_scope_without_expansion(chat_data):
    from app.modules.chat.service import create_conversation

    data = chat_data
    visible, hidden = data.kb(), data.kb(member=False)
    for ids in [[], [visible, visible], [visible, hidden], [uuid4()]]:
        with data.factory() as db, pytest.raises(AuthError):
            create_conversation(db, data.actor, ids, "request")
    with data.factory() as db:
        assert db.scalars(select(Conversation)).all() == []


def test_soft_delete_owner_admin_only_and_history_hidden(chat_data):
    from app.modules.chat.service import delete_conversation, get_conversation, list_messages

    data = chat_data
    conversation = data.conversation()
    reservation = data.reserve(conversation)
    agent = data.person("agent")
    with data.factory() as db, pytest.raises(AuthError):
        delete_conversation(db, agent, conversation.id, "delete", data_helpers.NOW)
    with data.factory() as db:
        delete_conversation(db, data.actor, conversation.id, "delete", data_helpers.NOW)
        db.commit()
    with data.factory() as db:
        assert db.get(Conversation, conversation.id).deleted_at is not None
        assert db.get(Message, reservation.assistant_message_id).status == "cancelled"
        assert db.get(Conversation, conversation.id).generation_token is None
        for fn in [get_conversation, list_messages]:
            with pytest.raises(AuthError):
                fn(db, data.actor, conversation.id)
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "conversation.delete"))


@pytest.mark.parametrize("mode", ["queued", "human"])
def test_owner_text_modes_and_admin_cannot_impersonate(chat_data, mode):
    from app.modules.chat.service import add_text_message

    data = chat_data
    conversation = data.conversation()
    admin = data.person("admin")
    with data.factory() as db:
        db.execute(update(Conversation).where(Conversation.id == conversation.id).values(mode=mode))
        db.commit()
    with data.factory() as db:
        message = add_text_message(db, data.actor, conversation.id, "留言", uuid4(), "req")
        db.commit()
        assert message.role == "user"
        assert message.status == "complete"
    with data.factory() as db, pytest.raises(AuthError):
        add_text_message(db, admin, conversation.id, "冒名", uuid4(), "req")


@pytest.mark.parametrize("mode", ["bot", "closed"])
def test_ordinary_text_rejects_wrong_mode(chat_data, mode):
    from app.modules.chat.service import add_text_message

    data = chat_data
    conversation = data.conversation()
    with data.factory() as db:
        db.execute(update(Conversation).where(Conversation.id == conversation.id).values(mode=mode))
        db.commit()
    with data.factory() as db, pytest.raises(AuthError) as error:
        add_text_message(db, data.actor, conversation.id, "留言", uuid4(), "req")
    assert error.value.status == 409


def test_transitions_cancel_generation_and_cas_prevents_second_claim(chat_data):
    from app.modules.chat.service import transition_mode

    data = chat_data
    conversation = data.conversation()
    reservation = data.reserve(conversation)
    agent = data.person("agent")
    with data.factory() as db:
        transition_mode(
            db,
            data.actor,
            conversation.id,
            expected_mode="bot",
            next_mode="queued",
            assigned_agent_id=None,
            request_id="queue",
        )
        db.commit()
    assert data.finish(reservation) is False
    with data.factory() as db:
        assert db.get(Message, reservation.assistant_message_id).status == "cancelled"
        transition_mode(
            db,
            agent,
            conversation.id,
            expected_mode="queued",
            next_mode="human",
            assigned_agent_id=agent.user_id,
            request_id="claim",
        )
        db.commit()
    with data.factory() as db, pytest.raises(AuthError) as error:
        transition_mode(
            db,
            data.person("agent"),
            conversation.id,
            expected_mode="queued",
            next_mode="human",
            assigned_agent_id=agent.user_id,
            request_id="claim",
        )
    assert error.value.status == 409
    with data.factory() as db:
        transition_mode(
            db,
            agent,
            conversation.id,
            expected_mode="human",
            next_mode="closed",
            assigned_agent_id=agent.user_id,
            request_id="close",
        )
        db.commit()
    with pytest.raises(AuthError):
        data.reserve(conversation)


def test_stale_admin_and_disabled_user_cannot_read(chat_data):
    from app.modules.chat.service import get_conversation

    data = chat_data
    conversation = data.conversation()
    admin = data.person("admin")
    with data.factory() as db:
        db.execute(update(User).where(User.id == admin.user_id).values(role="user"))
        db.execute(update(User).where(User.id == data.actor.user_id).values(is_active=False))
        db.commit()
    for actor in [admin, data.actor]:
        with data.factory() as db, pytest.raises(AuthError):
            get_conversation(db, actor, conversation.id)


@pytest.mark.parametrize("role", ["agent", "admin"])
def test_any_active_role_can_use_own_bot_conversation_but_not_impersonate(chat_data, role):
    data = chat_data
    actor = data.person(role)
    own = data.conversation(actor)
    reservation = data.reserve(own, actor=actor)
    assert reservation.actor == actor
    assert data.finish(reservation)
    other = data.conversation()
    with pytest.raises(AuthError):
        data.reserve(other, actor=actor)


def test_assigned_agent_can_only_send_in_human_and_cannot_delete(chat_data):
    from app.modules.chat.service import add_text_message, delete_conversation

    data = chat_data
    conversation = data.conversation()
    agent = data.person("agent")
    with data.factory() as db:
        db.execute(
            update(Conversation)
            .where(Conversation.id == conversation.id)
            .values(assigned_agent_id=agent.user_id, mode="human")
        )
        db.commit()
    with data.factory() as db:
        message = add_text_message(db, agent, conversation.id, "人工回复", uuid4(), "agent")
        assert message.role == "agent"
        assert message.author_id == agent.user_id
        db.commit()
    with data.factory() as db, pytest.raises(AuthError) as error:
        delete_conversation(db, agent, conversation.id, "delete", data_helpers.NOW)
    assert error.value.status == 403


def test_service_mutations_are_rollbackable_by_caller(chat_data):
    from app.modules.chat.service import create_conversation

    data = chat_data
    kb = data.kb()
    with data.factory() as db:
        conversation = create_conversation(db, data.actor, [kb], "rollback")
        identifier = conversation.id
        db.rollback()
    with data.factory() as db:
        assert db.get(Conversation, identifier) is None


def test_assigned_agent_without_human_or_closed_state_cannot_read(chat_data):
    from app.modules.chat.service import get_conversation, list_conversations

    data = chat_data
    conversation, agent = data.conversation(), data.person("agent")
    with data.factory() as db:
        db.execute(
            update(Conversation)
            .where(Conversation.id == conversation.id)
            .values(assigned_agent_id=agent.user_id, mode="queued")
        )
        db.commit()
    with data.factory() as db:
        assert list_conversations(db, agent)["total"] == 0
        with pytest.raises(AuthError) as error:
            get_conversation(db, agent, conversation.id)
        assert error.value.status == 404
