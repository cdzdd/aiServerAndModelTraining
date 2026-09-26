"""Explicit authenticated chat + BGE + cloud smoke, excluded from ordinary pytest."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.config import Settings
from app.modules.chat.models import GenerationUsage, Message
from app.modules.ingestion.worker import claim_job
from app.modules.ingestion.worker import process_job as parse_job
from app.modules.providers.config import ModelSettings
from app.modules.providers.factory import create_provider
from app.modules.retrieval.embedding import MODEL_REVISION, BGEEmbedder
from app.modules.retrieval.indexing import process_job as index_job
from tests.auth.conftest import csrf
from tests.knowledge.conftest import create_kb, members
from tests.rag import smoke_real_rag as fixtures

admin = fixtures.admin
auth_app = fixtures.auth_app
client = fixtures.client
user = fixtures.user
reader = fixtures.reader
clean_smoke = fixtures.clean_smoke


def test_authenticated_chat_real_sources_history_and_revocation(client, admin, reader, auth_app):
    config_path = os.environ.get("RAG_SMOKE_CONFIG")
    assert config_path, "Explicit RAG_SMOKE_CONFIG and cloud-call authorization required"
    local = Settings()
    cloud = ModelSettings(
        _env_file=config_path,
        model_provider="cloud",
        model_disable_thinking=True,
        model_max_output_tokens=512,
    )
    settings = auth_app.state.settings
    settings.embedding_model_path = local.embedding_model_path
    settings.embedding_tokenizer_path = local.embedding_tokenizer_path
    kb = create_kb(client)
    other, person = reader
    assert members(client, kb, [person["id"]]).status_code == 200
    passage = (
        "本资料是虚构校园样例。图书馆在期末考试周每天早上八点开放，"
        "晚上十一点闭馆。普通教学周晚上九点闭馆。"
    )
    upload = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("图书馆.txt", passage.encode("utf-8"))},
        headers=csrf(client),
    )
    assert upload.status_code == 202
    factory = auth_app.state.session_factory
    parse_job(factory, settings, claim_job(factory))
    embedder = BGEEmbedder(local.embedding_model_path).load()
    while job := claim_job(factory, kind="index"):
        index_job(factory, settings, job, embedder=embedder)
    # Preserve the app-created real RAG/retrieval and its app-specific database binding.
    retrieval = auth_app.state.chat_rag.retriever.__self__
    assert retrieval.session_factory is factory
    retrieval.embedder = embedder
    retrieval.threshold = local.retrieval_threshold
    observed = fixtures.ObservedProvider(create_provider(cloud))
    auth_app.state.chat_rag.provider = observed
    result = other.post(
        "/api/v1/conversations",
        json={"kb_ids": [kb["id"]]},
        headers=csrf(other),
    )
    assert result.status_code == 201
    cid = result.json()["id"]
    cases = []
    destination = Path(__file__).resolve().parents[3] / ".local/real-chat-smoke.json"

    def save():
        destination.write_text(
            json.dumps(
                {
                    "utc": datetime.now(UTC).isoformat(),
                    "model": cloud.model_id,
                    "embedding_revision": MODEL_REVISION,
                    "synthetic_fixture_only": True,
                    "actual_cloud_calls": len(observed.calls),
                    "calls": observed.calls,
                    "cases": cases,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    for question, expected in (
        ("期末考试周图书馆晚上几点关门？", "十一点"),
        ("普通教学周呢？", "九点"),
    ):
        key = str(uuid4())
        started = perf_counter()
        response = other.post(
            f"/api/v1/conversations/{cid}/messages/stream",
            headers=csrf(other),
            json={"content": question, "client_message_id": key},
        )
        events = []
        for block in response.text.strip().split("\n\n"):
            lines = block.splitlines()
            events.append({"event": lines[0][7:], "data": json.loads(lines[1][6:])})
        cases.append({"question": question, "seconds": perf_counter() - started, "events": events})
        save()
        assert response.status_code == 200
        assert [item["event"] for item in events] == ["meta", "delta", "citations", "done"]
        assert expected in events[1]["data"]["text"]
        assert events[2]["data"]["items"][0]["source_id"] == upload.json()["document_id"]
        assert events[-1]["data"]["answer_status"] == "answered"
        duplicate = other.post(
            f"/api/v1/conversations/{cid}/messages/stream",
            headers=csrf(other),
            json={"content": question, "client_message_id": key},
        )
        assert duplicate.status_code == 409
    assert len(observed.calls) == 3
    history = other.get(f"/api/v1/conversations/{cid}/messages").json()
    assert history["total"] == 4
    assert [item["role"] for item in history["items"]] == ["user", "assistant", "user", "assistant"]
    assert all(item["status"] == "complete" for item in history["items"])
    with factory() as db:
        usage = list(
            db.scalars(select(GenerationUsage).where(GenerationUsage.conversation_id == UUID(cid)))
        )
        assert len(usage) == 2 and all(item.outcome == "complete" for item in usage)
        assert all(item.total_tokens is not None for item in usage)
    assert members(client, {**kb, "version": kb["version"] + 1}, []).status_code == 200
    hidden = other.get(f"/api/v1/conversations/{cid}/messages").json()["items"]
    for item in hidden:
        if item["role"] == "assistant":
            assert item["evidence_hidden"] and item["citations"] == []
            assert "九点" not in item["content"] and "十一点" not in item["content"]
    with factory() as db:
        persisted = list(
            db.scalars(
                select(Message).where(
                    Message.conversation_id == UUID(cid),
                    Message.role == "assistant",
                )
            )
        )
        assert len(persisted) == 2 and all(item.status == "complete" for item in persisted)
        assert any("十一点" in item.content for item in persisted)
    cases.append(
        {
            "duplicate_keys": "rejected_without_extra_calls",
            "persisted_messages": 4,
            "accepted_requests": 2,
            "revoked_history_hidden": True,
        }
    )
    save()
    print(json.dumps({"actual_cloud_calls": len(observed.calls), "report": str(destination)}))
