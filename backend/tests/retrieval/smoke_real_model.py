"""Explicit-only real BGE smoke: pytest tests/retrieval/smoke_real_model.py -q -s."""
import asyncio
import json
from pathlib import Path
from time import perf_counter
from uuid import UUID

import pytest
from sqlalchemy import select, text

from app.core.config import Settings
from app.modules.auth.schemas import Actor
from app.modules.ingestion.models import Chunk, Document, IngestionJob
from app.modules.ingestion.worker import claim_job
from app.modules.ingestion.worker import process_job as parse_job
from app.modules.retrieval.embedding import DIMENSION, MODEL_ID, MODEL_REVISION, BGEEmbedder
from app.modules.retrieval.indexing import process_job as index_job
from app.modules.retrieval.service import RetrievalService
from tests.auth.conftest import csrf
from tests.ingestion import conftest as fixtures
from tests.knowledge.conftest import create_faq, create_kb, members

admin = fixtures.admin
auth_app = fixtures.auth_app
client = fixtures.client
user = fixtures.user
reader = fixtures.reader


@pytest.fixture(autouse=True)
def clean_smoke(migrated_engine):
    with migrated_engine.begin() as db:
        for table in ("chunks", "ingestion_jobs", "document_revisions", "documents"):
            db.execute(text(f"DELETE FROM {table}"))


def test_real_upload_parse_index_search(client, admin, reader, auth_app):
    config = Settings()
    assert config.embedding_model_path, "Configure the downloaded pinned model first"
    settings = auth_app.state.settings
    settings.embedding_model_path = config.embedding_model_path
    settings.embedding_tokenizer_path = config.embedding_tokenizer_path
    factory = auth_app.state.session_factory
    kb = create_kb(client)
    _, person = reader
    assert members(client, kb, [person["id"]]).status_code == 200
    library = (
        "本资料是虚构校园样例。图书馆在期末考试周每天早上八点开放，"
        "晚上十一点闭馆。普通教学周晚上九点闭馆。"
    )
    cafeteria = (
        "本资料是虚构校园样例。学生食堂工作日提供午餐，"
        "营业时间为十一点至十三点，套餐价格为十五元。"
    )
    ids = []
    for filename, passage in (("图书馆.txt", library), ("食堂.txt", cafeteria)):
        response = client.post(
            f"/api/v1/knowledge-bases/{kb['id']}/documents",
            files={"file": (filename, passage.encode("utf-8"))}, headers=csrf(client),
        )
        assert response.status_code == 202
        ids.append(UUID(response.json()["document_id"]))
        parse_job(factory, settings, claim_job(factory))
    faq = create_faq(
        client, kb, question="校园卡丢失后如何补办？",
        answer="本资料是虚构校园样例。请先通过校园卡服务平台挂失，再携带学生证到学生服务大厅一号窗口申请补办。",
    )
    start = perf_counter()
    embedder = BGEEmbedder(config.embedding_model_path).load()
    load_seconds = perf_counter() - start
    start = perf_counter()
    indexed = 0
    while job := claim_job(factory, kind="index"):
        index_job(factory, settings, job, embedder=embedder)
        indexed += 1
    index_seconds = perf_counter() - start
    with factory() as db:
        for doc_id in ids:
            doc = db.get(Document, doc_id)
            assert doc.status == "ready" and doc.active_revision_id == doc.candidate_revision_id
        assert all(job.state == "succeeded" for job in db.scalars(select(IngestionJob)))
        vectors = list(db.scalars(select(Chunk.embedding).where(Chunk.kb_id == UUID(kb["id"]))))
        assert len(vectors) == 3 and all(len(vector) == DIMENSION for vector in vectors)
    actor = Actor(user_id=UUID(person["id"]), role="user")
    scope = [UUID(kb["id"])]
    raw = RetrievalService(factory, embedder, threshold=-1)
    actual = RetrievalService(factory, embedder, threshold=config.retrieval_threshold)
    queries = [
        ("期末考试周图书馆晚上几点关门？", str(ids[0])),
        ("学校食堂的午餐套餐要多少钱？", str(ids[1])),
        ("我的校园卡丢了，应该去哪里补办？", faq["id"]),
        ("怎样维修家用燃气热水器？", None),
    ]
    results = []
    for query, expected in queries:
        start = perf_counter()
        hits = asyncio.run(raw.search(actor, scope, query))
        elapsed = perf_counter() - start
        filtered = asyncio.run(actual.search(actor, scope, query))
        if expected:
            assert str(hits[0].source_id) == expected
        results.append({
            "query": query, "expected_source": expected, "seconds": elapsed,
            "raw_top5": [hit.model_dump(mode="json") for hit in hits],
            "threshold_sources": [str(hit.source_id) for hit in filtered],
        })
    # Revoke membership after genuine encoding/indexing; every query must now be empty.
    assert members(client, {**kb, "version": kb["version"] + 1}, []).status_code == 200
    assert asyncio.run(actual.search(actor, scope, queries[0][0])) == []
    report = {
        "model": MODEL_ID, "revision": MODEL_REVISION, "dimensions": DIMENSION,
        "device": "cpu", "threshold": config.retrieval_threshold, "top_k": 5,
        "synthetic_fixture_only": True, "load_seconds": load_seconds,
        "index_seconds": index_seconds, "indexed_jobs": indexed,
        "documents": [library, cafeteria],
        "faq": {"question": faq["question"], "answer": faq["answer"]},
        "results": results, "revocation": "passed",
    }
    destination = Path(__file__).resolve().parents[3] / ".local/real-retrieval-smoke.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    for result in results:
        if result["expected_source"]:
            assert result["threshold_sources"], "Default threshold rejected relevant query"
            assert result["threshold_sources"][0] == result["expected_source"]
        else:
            assert result["threshold_sources"] == [], "Unrelated query must have no evidence"
