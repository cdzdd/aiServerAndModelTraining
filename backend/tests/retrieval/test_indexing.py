from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text

from app.modules.ingestion.models import Chunk, Document, IngestionJob
from app.modules.ingestion.worker import claim_job
from app.modules.ingestion.worker import process_job as parse_job
from app.modules.knowledge.models import FAQ, KnowledgeBase
from tests.auth.conftest import csrf
from tests.ingestion import conftest as fixtures
from tests.ingestion.test_uploads import upload
from tests.ingestion.test_worker import tokenizer
from tests.knowledge.conftest import create_faq, create_kb

admin = fixtures.admin
auth_app = fixtures.auth_app
client = fixtures.client
user = fixtures.user


@pytest.fixture(autouse=True)
def clean_indexing(migrated_engine):
    with migrated_engine.begin() as db:
        for table in ("chunks", "ingestion_jobs", "document_revisions", "documents"):
            db.execute(text(f"DELETE FROM {table}"))


class FixedEmbedder:
    def __init__(self, callback=None):
        self.callback = callback
        self.calls = 0

    def encode_passages(self, texts):
        self.calls += 1
        if self.callback:
            self.callback(self.calls)
        return [[1.0] + [0.0] * 511 for _ in texts]


def index_job(factory, settings, job, embedder=None):
    from app.modules.retrieval.indexing import process_job

    process_job(factory, settings, job, embedder=embedder or FixedEmbedder(), tokenizer=tokenizer())


def parsed(client, auth_app, kb=None, content=b"library hours"):
    data = upload(client, kb or create_kb(client), content=content).json()
    factory = auth_app.state.session_factory
    parse_job(factory, auth_app.state.settings, claim_job(factory), tokenizer=tokenizer())
    return UUID(data["document_id"])


def test_document_index_activates_atomically_preserves_ids_and_is_idempotent(
    client, admin, auth_app
):
    doc_id = parsed(client, auth_app)
    factory = auth_app.state.session_factory
    with factory() as db:
        ids = list(db.scalars(select(Chunk.id).where(Chunk.document_id == doc_id)))
    claimed = claim_job(factory, kind="index")
    index_job(factory, auth_app.state.settings, claimed)
    index_job(factory, auth_app.state.settings, claimed)
    with factory() as db:
        doc = db.get(Document, doc_id)
        assert doc.status == "ready"
        assert doc.active_revision_id == doc.candidate_revision_id
        chunks = list(db.scalars(select(Chunk).where(Chunk.document_id == doc_id)))
        assert [c.id for c in chunks] == ids
        assert all(
            len(c.embedding) == 512 and c.embedding_model and c.embedding_version for c in chunks
        )
        assert db.get(IngestionJob, claimed.id).state == "succeeded"


def test_faq_create_enqueues_once_and_indexes_captured_version(client, admin, auth_app):
    faq = create_faq(client, create_kb(client))
    factory = auth_app.state.session_factory
    claimed = claim_job(factory, kind="index")
    assert claimed is not None, "enabled FAQ must queue index work"
    assert claimed.faq_version == 1
    index_job(factory, auth_app.state.settings, claimed)
    with factory() as db:
        assert db.get(FAQ, UUID(faq["id"])).indexed_version == 1
        chunk = db.scalar(select(Chunk).where(Chunk.faq_id == UUID(faq["id"])))
        assert chunk.text == faq["question"] + "\n" + faq["answer"]
        assert len(chunk.embedding) == 512
        assert chunk.title == faq["question"]


def test_second_batch_failure_preserves_old_active_and_writes_no_partial_vectors(
    client, admin, auth_app
):
    from app.modules.retrieval.embedding import EmbeddingError

    doc_id = parsed(client, auth_app)
    factory = auth_app.state.session_factory
    index_job(factory, auth_app.state.settings, claim_job(factory, kind="index"))
    with factory() as db:
        old = db.get(Document, doc_id).active_revision_id
    response = client.post(
        f"/api/v1/documents/{doc_id}/revisions",
        files={"file": ("new.txt", ("words " * 6500).encode())},
        headers=csrf(client),
    )
    assert response.status_code == 202
    parse_job(factory, auth_app.state.settings, claim_job(factory), tokenizer=tokenizer())

    def fail_second(call):
        if call == 2:
            raise EmbeddingError("ENCODE_FAILED")

    claimed = claim_job(factory, kind="index")
    index_job(factory, auth_app.state.settings, claimed, FixedEmbedder(fail_second))
    with factory() as db:
        doc = db.get(Document, doc_id)
        assert doc.active_revision_id == old
        assert doc.status == "failed"
        chunks = list(
            db.scalars(select(Chunk).where(Chunk.revision_id == doc.candidate_revision_id))
        )
        assert len(chunks) > 16
        assert all(c.embedding is None for c in chunks)
        assert db.get(IngestionJob, claimed.id).state == "failed"


def test_reclaimed_token_fences_stale_indexer(client, admin, auth_app):
    doc_id = parsed(client, auth_app)
    factory = auth_app.state.session_factory
    stale = claim_job(factory, kind="index")
    with factory() as db:
        db.get(IngestionJob, stale.id).lease_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    fresh = claim_job(factory, kind="index")
    index_job(factory, auth_app.state.settings, stale)
    with factory() as db:
        assert db.get(Document, doc_id).active_revision_id is None
        assert db.get(IngestionJob, stale.id).lease_token == fresh.lease_token
    index_job(factory, auth_app.state.settings, fresh)
    with factory() as db:
        assert db.get(Document, doc_id).status == "ready"


@pytest.mark.parametrize("disable", [False, True])
def test_faq_changed_during_embedding_cannot_activate_old_version(client, admin, auth_app, disable):
    faq = create_faq(client, create_kb(client))
    factory = auth_app.state.session_factory
    claimed = claim_job(factory, kind="index")
    assert claimed is not None

    def edit(_):
        response = client.patch(
            f"/api/v1/faqs/{faq['id']}",
            json={"expected_version": 1, "answer": "changed answer", "is_active": not disable},
            headers=csrf(client),
        )
        assert response.status_code == 200

    index_job(factory, auth_app.state.settings, claimed, FixedEmbedder(edit))
    with factory() as db:
        current = db.get(FAQ, UUID(faq["id"]))
        assert current.indexed_version is None
        assert db.get(IngestionJob, claimed.id).error_code == "SUPERSEDED"
        queued = list(
            db.scalars(
                select(IngestionJob).where(
                    IngestionJob.faq_id == current.id, IngestionJob.faq_version == 2
                )
            )
        )
        assert len(queued) == (0 if disable else 1)


def test_kb_restore_requeues_cancelled_faq(client, admin, auth_app):
    kb = create_kb(client)
    faq = create_faq(client, kb)
    factory = auth_app.state.session_factory
    claimed = claim_job(factory, kind="index")
    assert claimed is not None
    with factory() as db:
        db.get(KnowledgeBase, UUID(kb["id"])).is_active = False
        db.commit()
    index_job(factory, auth_app.state.settings, claimed)
    response = client.patch(
        f"/api/v1/knowledge-bases/{kb['id']}",
        json={"expected_version": 1, "is_active": True},
        headers=csrf(client),
    )
    assert response.status_code == 200
    restored = claim_job(factory, kind="index")
    assert restored is not None and restored.id == claimed.id
    index_job(factory, auth_app.state.settings, restored)
    with factory() as db:
        assert db.get(FAQ, UUID(faq["id"])).indexed_version == 1


def test_index_error_is_safe_and_actionable_in_document_summary(client, admin, auth_app):
    from app.modules.retrieval.embedding import EmbeddingError

    doc_id = parsed(client, auth_app)

    def fail(_):
        raise EmbeddingError("ENCODE_FAILED")

    index_job(
        auth_app.state.session_factory,
        auth_app.state.settings,
        claim_job(auth_app.state.session_factory, kind="index"),
        FixedEmbedder(fail),
    )
    result = client.get(f"/api/v1/documents/{doc_id}").json()
    assert result["status"] == "failed"
    assert result["latest_job"]["error_code"] == "ENCODE_FAILED"
    assert result["latest_job"]["error_message"]


def test_index_commit_crash_rolls_back_all_vectors_then_recovers(client, admin, auth_app):
    from sqlalchemy import event

    doc_id = parsed(client, auth_app)
    factory = auth_app.state.session_factory
    claimed = claim_job(factory, kind="index")

    def crash(session, context):
        if any(isinstance(item, Chunk) for item in session.dirty):
            raise RuntimeError("simulated index commit crash")

    event.listen(factory.class_, "after_flush", crash)
    try:
        with pytest.raises(RuntimeError, match="simulated index commit crash"):
            index_job(factory, auth_app.state.settings, claimed)
    finally:
        event.remove(factory.class_, "after_flush", crash)
    with factory() as db:
        doc = db.get(Document, doc_id)
        assert doc.active_revision_id is None
        assert db.scalar(select(Chunk).where(Chunk.document_id == doc_id)).embedding is None
        job = db.get(IngestionJob, claimed.id)
        assert job.state == "running"
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    index_job(factory, auth_app.state.settings, claim_job(factory, kind="index"))
    with factory() as db:
        assert db.get(Document, doc_id).status == "ready"


def test_lease_reclaimed_during_encode_prevents_stale_writes(client, admin, auth_app):
    doc_id = parsed(client, auth_app)
    factory = auth_app.state.session_factory
    claimed = claim_job(factory, kind="index")
    fresh = []

    def reclaim(_):
        with factory() as db:
            db.get(IngestionJob, claimed.id).lease_until = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        fresh.append(claim_job(factory, kind="index"))

    index_job(factory, auth_app.state.settings, claimed, FixedEmbedder(reclaim))
    with factory() as db:
        assert db.get(Document, doc_id).active_revision_id is None
        assert db.get(IngestionJob, claimed.id).lease_token == fresh[0].lease_token
        assert db.scalar(select(Chunk).where(Chunk.document_id == doc_id)).embedding is None
    index_job(factory, auth_app.state.settings, fresh[0])
    with factory() as db:
        assert db.get(Document, doc_id).status == "ready"


def test_reindex_same_document_keeps_chunk_ids(client, admin, auth_app):
    doc_id = parsed(client, auth_app)
    factory = auth_app.state.session_factory
    index_job(factory, auth_app.state.settings, claim_job(factory, kind="index"))
    with factory() as db:
        ids = list(db.scalars(select(Chunk.id).where(Chunk.document_id == doc_id)))
    assert (
        client.post(f"/api/v1/documents/{doc_id}/reindex", headers=csrf(client)).status_code == 202
    )
    index_job(factory, auth_app.state.settings, claim_job(factory, kind="index"))
    with factory() as db:
        assert list(db.scalars(select(Chunk.id).where(Chunk.document_id == doc_id))) == ids
        assert db.get(Document, doc_id).status == "ready"


def test_killed_index_worker_is_recovered_after_expiry(client, admin, auth_app):
    import subprocess
    import sys

    doc_id = parsed(client, auth_app)
    script = """import sys, time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.modules.ingestion.worker import claim_job
engine = create_engine(sys.stdin.read(), connect_args={'connect_timeout': 3})
job = claim_job(sessionmaker(engine, expire_on_commit=False), kind='index')
print(job.id, flush=True)
time.sleep(60)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        try:
            process.communicate(
                input=auth_app.state.engine.url.render_as_string(hide_password=False), timeout=2
            )
        except subprocess.TimeoutExpired:
            process.kill()
        output, errors = process.communicate(timeout=5)
        assert output.strip(), errors
        job_id = UUID(output.strip())
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    factory = auth_app.state.session_factory
    with factory() as db:
        job = db.get(IngestionJob, job_id)
        assert job.state == "running"
        assert db.get(Document, doc_id).active_revision_id is None
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    recovered = claim_job(factory, kind="index")
    assert recovered.id == job_id and recovered.attempts == 2
    index_job(factory, auth_app.state.settings, recovered)
    with factory() as db:
        assert db.get(Document, doc_id).status == "ready"


def test_migration_backfills_enabled_faqs_once(database_url):
    from pathlib import Path
    from uuid import uuid4

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.schema import CreateSchema, DropSchema

    schema = "index_migration_" + uuid4().hex
    admin_engine = create_engine(database_url.get_secret_value(), hide_parameters=True)
    with admin_engine.begin() as db:
        db.execute(CreateSchema(schema))
    engine = create_engine(
        make_url(database_url.get_secret_value()).update_query_dict(
            {"options": f"-csearch_path={schema},public"}
        ),
        hide_parameters=True,
    )
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    kb_id, enabled_id, disabled_id = uuid4(), uuid4(), uuid4()
    try:
        with engine.begin() as db:
            config.attributes["connection"] = db
            command.upgrade(config, "006")
            db.execute(
                text("INSERT INTO knowledge_bases VALUES (:id, 'test', '', 'public', true, 1)"),
                {"id": kb_id},
            )
            for faq_id, active in ((enabled_id, True), (disabled_id, False)):
                db.execute(
                    text(
                        "INSERT INTO faqs (id,kb_id,question,answer,is_active,version,updated_at) "
                        "VALUES (:id,:kb,'q','a',:active,2,now())"
                    ),
                    {"id": faq_id, "kb": kb_id, "active": active},
                )
            command.upgrade(config, "007")
            command.upgrade(config, "007")
            rows = db.execute(text("SELECT faq_id,faq_version,state FROM ingestion_jobs")).all()
            assert rows == [(enabled_id, 2, "queued")]
            command.downgrade(config, "006")
            assert db.scalar(text("SELECT count(*) FROM faqs")) == 2
    finally:
        engine.dispose()
        with admin_engine.begin() as db:
            db.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


@pytest.mark.parametrize("active_version", ["none", "older", "candidate"])
def test_enable_cancelled_index_exposes_retry_and_preserves_active(
    client, admin, auth_app, active_version
):
    doc_id = parsed(client, auth_app)
    factory = auth_app.state.session_factory
    url = f"/api/v1/documents/{doc_id}"
    old_active = None
    if active_version != "none":
        index_job(factory, auth_app.state.settings, claim_job(factory, kind="index"))
        with factory() as db:
            old_active = db.get(Document, doc_id).active_revision_id
        if active_version == "older":
            response = client.post(
                url + "/revisions",
                files={"file": ("new.txt", b"updated library hours")},
                headers=csrf(client),
            )
            assert response.status_code == 202
            parse_job(factory, auth_app.state.settings, claim_job(factory), tokenizer=tokenizer())
        else:
            assert client.post(url + "/reindex", headers=csrf(client)).status_code == 202
    assert client.patch(url, json={"is_active": False}, headers=csrf(client)).status_code == 200
    cancelled = claim_job(factory, kind="index")
    index_job(factory, auth_app.state.settings, cancelled)
    response = client.patch(url, json={"is_active": True}, headers=csrf(client))
    assert response.status_code == 200
    restored = response.json()
    assert restored["status"] == "failed"
    assert restored["active_revision_id"] == (str(old_active) if old_active else None)
    assert restored["latest_job"]["error_code"] == "SUPERSEDED"
    retry = client.post(url + "/reindex", headers=csrf(client))
    assert retry.status_code == 202
    assert retry.json()["job_id"] == str(cancelled.id)
    index_job(factory, auth_app.state.settings, claim_job(factory, kind="index"))
    ready = client.get(url).json()
    assert ready["status"] == "ready"
    assert ready["active_revision_id"] == ready["candidate_revision_id"]


def test_enable_successfully_indexed_document_restores_ready(client, admin, auth_app):
    doc_id = parsed(client, auth_app)
    factory = auth_app.state.session_factory
    index_job(factory, auth_app.state.settings, claim_job(factory, kind="index"))
    url = f"/api/v1/documents/{doc_id}"
    assert client.patch(url, json={"is_active": False}, headers=csrf(client)).status_code == 200
    restored = client.patch(url, json={"is_active": True}, headers=csrf(client)).json()
    assert restored["status"] == "ready"
    assert restored["active_revision_id"] == restored["candidate_revision_id"]
