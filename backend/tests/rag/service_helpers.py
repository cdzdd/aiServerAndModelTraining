import asyncio
import json
from uuid import uuid4

from app.modules.auth.schemas import Actor
from app.modules.providers.schemas import LLMDelta
from app.modules.retrieval.schemas import SearchHit

ACTOR = Actor(user_id=uuid4(), role="user")
KB_IDS = [uuid4()]
QUOTE = "图书馆每天上午九点开放。"


def hit(text=QUOTE):
    return SearchHit(
        chunk_id=uuid4(),
        kb_id=KB_IDS[0],
        text=text,
        source_type="document",
        source_id=uuid4(),
        title="图书馆指南",
        score=0.9,
        revision_id=uuid4(),
        page_number=2,
        paragraph_number=3,
    )


def answer(index=1, quote=QUOTE, **extra):
    return json.dumps(
        {"status": "answered", "selections": [{"index": index, "quote": quote}], **extra},
        ensure_ascii=False,
    )


class ScriptedProvider:
    def __init__(self, *scripts):
        self.scripts = list(scripts)
        self.calls = []
        self.closed = 0

    async def stream(self, messages, *, max_tokens, temperature):
        self.calls.append((messages, max_tokens, temperature))
        script = self.scripts.pop(0)
        try:
            for item in script:
                if isinstance(item, float):
                    await asyncio.sleep(item)
                elif isinstance(item, Exception):
                    raise item
                else:
                    yield item
        finally:
            self.closed += 1


def complete(text, usage=None):
    return [LLMDelta(text=text), LLMDelta(finish_reason="stop", usage=usage)]


class Sources:
    def __init__(self, hits=(), *, valid=True):
        self.hits = list(hits)
        self.valid = valid
        self.searches = []
        self.checks = []

    async def search(self, actor, kb_ids, query, top_k=5):
        self.searches.append((actor, list(kb_ids), query, top_k))
        return list(self.hits)

    async def validate(self, actor, kb_ids, hits):
        self.checks.append((actor, list(kb_ids), hits))
        return self.valid


def collect(service, question="图书馆何时开放？", history=None):
    async def run():
        return [
            event async for event in service.stream_answer(ACTOR, KB_IDS, question, history or [])
        ]

    return asyncio.run(run())


def text_of(events):
    return "".join(event.payload["text"] for event in events if event.type == "delta")
