from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from tokenizers import Tokenizer, models, pre_tokenizers

from app.modules.ingestion.models import Chunk, Document, IngestionJob
from app.modules.ingestion.worker import claim_job, process_job
from tests.auth.conftest import csrf
from tests.ingestion.test_uploads import upload
from tests.knowledge.conftest import create_kb


def tokenizer():
    result = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    result.pre_tokenizer = pre_tokenizers.Whitespace()
    return result


def test_parse_is_atomic_idempotent_and_does_not_activate(client, admin, auth_app):
    kb = create_kb(client)
    document = upload(client, kb).json()
    factory = auth_app.state.session_factory
    job = claim_job(factory)
    assert str(job.id) == document["job_id"]
    assert claim_job(factory) is None
    process_job(factory, auth_app.state.settings, job, tokenizer=tokenizer())
    process_job(factory, auth_app.state.settings, job, tokenizer=tokenizer())
    with factory() as db:
        doc = db.get(Document, UUID(document["document_id"]))
        assert doc.status == "parsed"
        assert doc.active_revision_id is None
        assert (
            db.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id == doc.id))
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(IngestionJob)
                .where(IngestionJob.document_id == doc.id, IngestionJob.kind == "index")
            )
            == 1
        )
    assert claim_job(factory) is None  # index is reserved for 007


def test_expired_lease_reclaims_and_fences_old_worker(client, admin, auth_app):
    document = upload(client, create_kb(client)).json()
    factory = auth_app.state.session_factory
    first = claim_job(factory)
    with factory() as db:
        db.get(IngestionJob, first.id).lease_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    recovered = claim_job(factory)
    assert recovered.id == first.id
    assert recovered.attempts == 2
    process_job(factory, auth_app.state.settings, first, tokenizer=tokenizer())
    with factory() as db:
        assert db.get(IngestionJob, first.id).state == "running"
    process_job(factory, auth_app.state.settings, recovered, tokenizer=tokenizer())
    assert client.get("/api/v1/documents/" + document["document_id"]).json()["status"] == "parsed"


def test_disabled_document_is_not_revived_by_worker(client, admin, auth_app):
    document = upload(client, create_kb(client)).json()
    factory = auth_app.state.session_factory
    job = claim_job(factory)
    url = "/api/v1/documents/" + document["document_id"]
    client.patch(url, json={"is_active": False}, headers=csrf(client))
    process_job(factory, auth_app.state.settings, job, tokenizer=tokenizer())
    assert client.get(url).json()["status"] == "disabled"


def test_failed_candidate_keeps_old_active_and_retry_reuses_job(client, admin, auth_app):
    document = upload(client, create_kb(client)).json()
    factory = auth_app.state.session_factory
    job = claim_job(factory)
    process_job(factory, auth_app.state.settings, job, tokenizer=tokenizer())
    with factory() as db:
        doc = db.get(Document, UUID(document["document_id"]))
        old = doc.candidate_revision_id
        doc.active_revision_id = old
        doc.status = "ready"
        db.commit()
    url = "/api/v1/documents/" + document["document_id"]
    response = client.post(
        url + "/revisions", files={"file": ("broken.docx", b"broken")}, headers=csrf(client)
    )
    assert response.status_code == 202
    candidate = claim_job(factory)
    process_job(factory, auth_app.state.settings, candidate, tokenizer=tokenizer())
    detail = client.get(url).json()
    assert detail["status"] == "failed"
    assert detail["active_revision_id"] == str(old)
    assert detail["latest_job"]["error_code"] == "INVALID_FORMAT"
    retry = client.post(url + "/reindex", headers=csrf(client))
    assert retry.status_code == 202
    again = client.post(url + "/reindex", headers=csrf(client))
    assert retry.json() == again.json()


def test_chunk_write_failure_rolls_back_then_recovers(client, admin, auth_app):
    import pytest
    from sqlalchemy import event

    uploaded = upload(client, create_kb(client)).json()
    factory = auth_app.state.session_factory
    claimed = claim_job(factory)

    def crash_after_chunk_flush(session, context):
        if any(isinstance(item, Chunk) for item in session.new):
            raise RuntimeError("simulated worker death after chunk flush")

    event.listen(factory.class_, "after_flush", crash_after_chunk_flush)
    try:
        with pytest.raises(RuntimeError, match="simulated worker death"):
            process_job(factory, auth_app.state.settings, claimed, tokenizer=tokenizer())
    finally:
        event.remove(factory.class_, "after_flush", crash_after_chunk_flush)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Chunk)) == 0
        job = db.get(IngestionJob, claimed.id)
        assert job.state == "running"
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    recovered = claim_job(factory)
    process_job(factory, auth_app.state.settings, recovered, tokenizer=tokenizer())
    detail = client.get("/api/v1/documents/" + uploaded["document_id"]).json()
    assert detail["status"] == "parsed"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Chunk)) == 1
        assert (
            db.scalar(
                select(func.count()).select_from(IngestionJob).where(IngestionJob.kind == "index")
            )
            == 1
        )


def test_concurrent_claims_do_not_duplicate(client, admin, auth_app):
    from concurrent.futures import ThreadPoolExecutor

    upload(client, create_kb(client))
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim_job(auth_app.state.session_factory), range(2)))
    assert sum(claim is not None for claim in claims) == 1


def test_parser_child_hard_memory_limit():
    import subprocess
    import sys

    script = """from app.modules.ingestion.resource_limits import limit_memory
limit_memory()
try:
    content = bytearray(600 * 1024 * 1024)
except MemoryError:
    print('bounded')
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "bounded"


def test_bounded_parser_timeout_is_safe(tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace

    import pytest

    from app.modules.ingestion.parsers import ParseError
    from app.modules.ingestion.worker import bounded_parse

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("parser", 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    settings = SimpleNamespace(
        upload_dir=tmp_path, embedding_tokenizer_path="", ingestion_parse_timeout=1
    )
    revision = SimpleNamespace(storage_key="file", file_type="txt")
    with pytest.raises(ParseError, match="PARSE_TIMEOUT"):
        bounded_parse(settings, revision)


def test_real_parser_child_uses_configured_tokenizer(tmp_path):
    from types import SimpleNamespace

    from app.modules.ingestion.worker import bounded_parse

    model = tokenizer()
    tokenizer_path = tmp_path / "tokenizer.json"
    model.save(str(tokenizer_path))
    (tmp_path / "file").write_text("校园服务手册", encoding="utf-8")
    settings = SimpleNamespace(
        upload_dir=tmp_path,
        embedding_tokenizer_path=str(tokenizer_path),
        ingestion_parse_timeout=15,
    )
    chunks = bounded_parse(settings, SimpleNamespace(storage_key="file", file_type="txt"))
    assert chunks[0].text == "校园服务手册"


def test_killed_worker_is_recovered_after_lease(client, admin, auth_app):
    import subprocess
    import sys

    uploaded = upload(client, create_kb(client)).json()
    script = """import sys, time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.modules.ingestion.worker import claim_job
engine = create_engine(sys.stdin.read(), connect_args={'connect_timeout': 3})
job = claim_job(sessionmaker(engine, expire_on_commit=False))
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
        assert uploaded["job_id"] in output, errors
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    factory = auth_app.state.session_factory
    with factory() as db:
        job = db.get(IngestionJob, UUID(uploaded["job_id"]))
        assert job.state == "running"
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    recovered = claim_job(factory)
    assert recovered.attempts == 2
    process_job(factory, auth_app.state.settings, recovered, tokenizer=tokenizer())
    assert client.get("/api/v1/documents/" + uploaded["document_id"]).json()["status"] == "parsed"


def test_disabled_knowledge_cannot_leave_document_processing(client, admin, auth_app):
    from app.modules.knowledge.models import KnowledgeBase

    kb = create_kb(client)
    uploaded = upload(client, kb).json()
    factory = auth_app.state.session_factory
    claimed = claim_job(factory)
    with factory() as db:
        db.get(KnowledgeBase, UUID(kb["id"])).is_active = False
        db.commit()
    process_job(factory, auth_app.state.settings, claimed, tokenizer=tokenizer())
    with factory() as db:
        doc = db.get(Document, UUID(uploaded["document_id"]))
        assert doc.status == "failed"
        assert db.get(IngestionJob, claimed.id).error_code == "SUPERSEDED"


def test_zero_token_candidate_fails_without_index_job(client, admin, auth_app):
    import os

    import pytest

    model_path = os.environ.get("EMBEDDING_TOKENIZER_PATH")
    if not model_path:
        pytest.skip("EMBEDDING_TOKENIZER_PATH is required for real BGE integration")
    auth_app.state.settings.embedding_tokenizer_path = model_path
    uploaded = upload(client, create_kb(client), content="\u200b\u200c\u200d".encode()).json()
    factory = auth_app.state.session_factory
    claimed = claim_job(factory)
    process_job(factory, auth_app.state.settings, claimed)
    detail = client.get("/api/v1/documents/" + uploaded["document_id"]).json()
    assert detail["status"] == "failed"
    assert detail["latest_job"]["error_code"] == "NO_TEXT"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Chunk)) == 0
        assert (
            db.scalar(
                select(func.count()).select_from(IngestionJob).where(IngestionJob.kind == "index")
            )
            == 0
        )
