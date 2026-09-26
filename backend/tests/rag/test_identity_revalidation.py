"""Identity changes committed during generation must prevent any evidence disclosure."""

import asyncio
import json

import pytest
from sqlalchemy import update
from sqlalchemy.orm import sessionmaker

from app.modules.auth.models import User
from app.modules.auth.schemas import Actor
from app.modules.providers.schemas import LLMDelta
from app.modules.rag.service import RAGService
from app.modules.retrieval.service import RetrievalService
from tests.retrieval.search_helpers import FixedEmbedder, SearchData


@pytest.mark.parametrize(
    "role,change",
    [
        ("admin", {"role": "user"}),
        ("user", {"is_active": False}),
        ("admin", None),
        ("user", None),
    ],
)
def test_identity_is_revalidated_after_generation_before_any_output(migrated_engine, role, change):
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    data = SearchData(factory)
    # An administrator reads the restricted KB without membership; the user is a member.
    kb = data.kb(member=role != "admin")
    quote = "图书馆每天上午九点开放。"
    data.document(kb, text=quote)
    with factory() as db:
        db.execute(update(User).where(User.id == data.actor.user_id).values(role=role))
        db.commit()
    actor = Actor(user_id=data.actor.user_id, role=role)
    retrieval = RetrievalService(factory, FixedEmbedder())

    class Provider:
        async def stream(self, messages, *, max_tokens, temperature):
            yield LLMDelta(
                text=json.dumps(
                    {
                        "status": "answered",
                        "selections": [{"index": 1, "quote": quote}],
                    },
                    ensure_ascii=False,
                )
            )
            if change is not None:
                # Independent connection commits after retrieval, just before the final stop.
                with migrated_engine.begin() as connection:
                    connection.execute(
                        update(User).where(User.id == actor.user_id).values(**change)
                    )
            yield LLMDelta(finish_reason="stop")

    async def run():
        service = RAGService(retrieval.search, retrieval.validate_hits, Provider())
        return [
            event
            async for event in service.stream_answer(
                actor,
                [kb],
                "图书馆何时开放？",
                [],
            )
        ]

    events = asyncio.run(run())
    if change is not None:
        assert [event.type for event in events] == ["error"]
        assert events[0].payload["code"] == "SOURCE_CHANGED"
        assert quote not in str(events)
    else:
        assert [event.type for event in events] == ["delta", "citations", "done"]
        assert quote in events[0].payload["text"]
        assert events[1].payload["items"][0]["quote"] == quote
        assert events[-1].payload["answer_status"] == "answered"
