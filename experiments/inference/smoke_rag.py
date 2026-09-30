"""Explicit real Ollama + BGE + production RAG smoke, outside default test collection."""

import asyncio
import json
import os
from contextlib import aclosing
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import UUID

from app.core.config import Settings
from app.modules.auth.schemas import Actor
from app.modules.ingestion.worker import claim_job
from app.modules.ingestion.worker import process_job as parse_job
from app.modules.providers.config import ModelSettings
from app.modules.providers.factory import create_provider
from app.modules.providers.schemas import LLMMessage
from app.modules.rag.prompts import PROMPT_VERSION
from app.modules.rag.service import RAGService
from app.modules.retrieval.embedding import MODEL_REVISION, BGEEmbedder
from app.modules.retrieval.indexing import process_job as index_job
from app.modules.retrieval.service import RetrievalService
from tests import conftest as database_fixtures
from tests.auth.conftest import csrf
from tests.knowledge.conftest import create_kb, members
from tests.rag import smoke_real_rag as existing

# Reuse established isolated-schema/auth fixtures; no production bypasses or test switches.
database_url = database_fixtures.database_url
migrated_engine = database_fixtures.migrated_engine
admin = existing.admin
auth_app = existing.auth_app
client = existing.client
user = existing.user
reader = existing.reader
clean_smoke = existing.clean_smoke


def test_real_ollama_rag_citations_history_refusal_and_permission(
    client,
    admin,
    reader,
    auth_app,
):
    config_path = os.environ.get("OLLAMA_SMOKE_CONFIG")
    assert config_path, "Set OLLAMA_SMOKE_CONFIG explicitly; no implicit real model runs"
    model = ModelSettings(_env_file=config_path, model_provider="ollama")
    config = Settings()
    settings = auth_app.state.settings
    settings.embedding_model_path = config.embedding_model_path
    settings.embedding_tokenizer_path = config.embedding_tokenizer_path
    factory = auth_app.state.session_factory
    kb = create_kb(client)
    _, person = reader
    assert members(client, kb, [person["id"]]).status_code == 200
    passage = (
        "本资料是虚构校园样例。图书馆在期末考试周每天早上八点开放，"
        "晚上十一点闭馆。普通教学周晚上九点闭馆。"
    )
    uploaded = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("library.txt", passage.encode("utf-8"))},
        headers=csrf(client),
    )
    assert uploaded.status_code == 202
    parse_job(factory, settings, claim_job(factory))
    embedder = BGEEmbedder(config.embedding_model_path).load()
    while job := claim_job(factory, kind="index"):
        index_job(factory, settings, job, embedder=embedder)
    retrieval = RetrievalService(factory, embedder, config.retrieval_threshold)
    observed = existing.ObservedProvider(create_provider(model))
    service = RAGService(retrieval.search, retrieval.validate_hits, observed)
    actor = Actor(user_id=UUID(person["id"]), role="user")
    scope = [UUID(kb["id"])]
    destination = Path(__file__).resolve().parents[2] / ".local/ollama-rag-smoke.json"
    cases = []

    def save():
        destination.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "utc": datetime.now(UTC).isoformat(),
            "provider": "ollama",
            "model": model.model_id,
            "num_ctx": model.ollama_num_ctx,
            "prompt_version": PROMPT_VERSION,
            "embedding_revision": MODEL_REVISION,
            "threshold": config.retrieval_threshold,
            "synthetic_fixture_only": True,
            "actual_model_calls": len(observed.calls),
            "calls": observed.calls,
            "cases": cases,
        }
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    async def collect(question, history, allowed_scope):
        async with aclosing(
            service.stream_answer(actor, allowed_scope, question, history)
        ) as stream:
            return [event async for event in stream]

    def run(name, question, *, history=None):
        before, started = len(observed.calls), perf_counter()
        events = asyncio.run(collect(question, history or [], scope))
        cases.append(
            {
                "name": name,
                "question": question,
                "elapsed_seconds": perf_counter() - started,
                "model_calls": len(observed.calls) - before,
                "events": [event.model_dump(mode="json") for event in events],
            }
        )
        save()  # Preserve failures, too; never make a partially-run suite look complete.
        answer = "".join(event.payload["text"] for event in events if event.type == "delta")
        return events, answer

    question = "期末考试周图书馆晚上几点关门？"
    first_answer = None
    for number in range(3):
        events, answer = run(f"library_{number + 1}", question)
        assert events[-1].type == "done" and events[-1].payload["answer_status"] == "answered"
        assert "十一点" in answer
        assert any(event.type == "citations" and event.payload["items"] for event in events)
        first_answer = answer
    history = [
        LLMMessage(role="user", content=question),
        LLMMessage(role="assistant", content=first_answer),
    ]
    events, answer = run("followup", "普通教学周呢？", history=history)
    assert events[-1].type == "done" and events[-1].payload["answer_status"] == "answered"
    assert "九点" in answer and cases[-1]["model_calls"] == 2
    events, _ = run("unrelated", "怎样维修家用燃气热水器？")
    assert events[-1].type == "done" and events[-1].payload["answer_status"] == "no_answer"
    assert cases[-1]["model_calls"] == 0
    assert members(client, {**kb, "version": kb["version"] + 1}, []).status_code == 200
    events, _ = run("revoked", question)
    assert events[-1].type == "done" and events[-1].payload["answer_status"] == "no_answer"
    assert cases[-1]["model_calls"] == 0
    save()
    print(
        json.dumps(
            {
                "cases": len(cases),
                "actual_model_calls": len(observed.calls),
                "report": str(destination),
            }
        )
    )
