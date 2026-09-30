# ruff: noqa: E402
"""Explicit offline BGE evaluation using real pgvector indexing and optional local RAG."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from experiments.evaluation.dataset import load_dataset
from experiments.evaluation.metrics import summarize
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import Settings
from app.modules.auth.models import User
from app.modules.auth.schemas import Actor
from app.modules.ingestion.models import Chunk, IngestionJob
from app.modules.knowledge.models import FAQ, KnowledgeBase
from app.modules.providers.config import ModelSettings
from app.modules.providers.factory import create_provider
from app.modules.providers.schemas import LLMMessage
from app.modules.rag.prompts import PROMPT_VERSION
from app.modules.rag.service import RAGService
from app.modules.retrieval.embedding import (
    MODEL_ID,
    MODEL_REVISION,
    BGEEmbedder,
)
from app.modules.retrieval.indexing import process_job
from app.modules.retrieval.reranker import LocalCrossEncoder
from app.modules.retrieval.service import RetrievalService


def stable_id(label):
    return uuid5(NAMESPACE_URL, "campus-synthetic-v1/" + label)


@contextmanager
def evaluation_database():
    # Always use the worktree's test DB. No development or production schema is touched.
    url = dotenv_values(ROOT / ".env").get("TEST_DATABASE_URL")
    if not url or make_url(url).database != "qa_test":
        raise ValueError("isolated qa_test TEST_DATABASE_URL is required")
    schema = "evaluation_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    engine = create_engine(
        make_url(url).update_query_dict({"options": f"-csearch_path={schema},public"}),
        hide_parameters=True,
    )
    try:
        with engine.begin() as connection:
            config = Config(str(ROOT / "backend/alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield sessionmaker(engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


def build_index(factory, dataset, settings, embedder):
    kbs = {source["kb"]: stable_id(source["kb"]) for source in dataset["sources"]}
    user_id = stable_id("evaluation-user")
    jobs = []
    with factory() as db:
        db.add(
            User(
                id=user_id,
                username="synthetic-evaluation",
                display_name="虚构教学评测",
                password_hash="unused",
            )
        )
        for name, kb_id in kbs.items():
            db.add(
                KnowledgeBase(
                    id=kb_id,
                    name=name,
                    visibility="restricted" if name.endswith("restricted") else "public",
                )
            )
        db.flush()
        for source in dataset["sources"]:
            source_id = stable_id(source["id"])
            db.add(
                FAQ(
                    id=source_id,
                    kb_id=kbs[source["kb"]],
                    question=source["title"],
                    answer=source["text"],
                    version=1,
                )
            )
            db.flush()
            # Fixture IDs remain stable; the normal index handler writes the real vectors.
            db.add(
                Chunk(
                    id=stable_id(source["id"] + "/chunk-0"),
                    kb_id=kbs[source["kb"]],
                    faq_id=source_id,
                    faq_version=1,
                    chunk_index=0,
                    text=source["title"] + "\n" + source["text"],
                    title=source["title"],
                )
            )
            job = IngestionJob(
                faq_id=source_id,
                faq_version=1,
                kind="index",
                state="running",
                lease_token=uuid4(),
                lease_until=datetime.now(UTC) + timedelta(seconds=90),
            )
            db.add(job)
            jobs.append(job)
        db.commit()
    for job in jobs:
        process_job(factory, settings, job, embedder=embedder)
        with factory() as db:
            if db.get(IngestionJob, job.id).state != "succeeded":
                raise RuntimeError("real BGE indexing failed")
    return Actor(user_id=user_id, role="user"), kbs


async def evaluate_case(case, actor, kb_ids, retriever, source_map, provider=None):
    started = time.perf_counter()
    row = {
        **case,
        "retrieved_sources": [],
        "hits": [],
        "generation_hits": [],
        "generation_query": None,
        "answer_status": None,
        "answer_text": "",
        "citation_sources": [],
        "citation_mapped": [],
        "citations": [],
        "usage": None,
        "unauthorized_sources": [],
        "rerank_status": "disabled",
        "error": None,
    }
    try:
        outcome = await retriever.search_detailed(actor, kb_ids, case["retrieval_query"], top_k=5)
        hits = outcome.hits
        row["hits"] = [hit.model_dump(mode="json") for hit in hits]
        row["retrieved_sources"] = [
            source_map.get(hit.source_id, str(hit.source_id)) for hit in hits
        ]
        row["rerank_status"] = outcome.rerank_status
        for hit in hits:
            if not await retriever.validate_hits(actor, kb_ids, [hit]):
                row["unauthorized_sources"].append(
                    source_map.get(hit.source_id, str(hit.source_id))
                )
        row["retrieval_latency_ms"] = (time.perf_counter() - started) * 1000
        if provider is not None:
            generation_hits = []

            async def traced_search(actor, scope, query, top_k=5):
                result = await retriever.search_detailed(actor, scope, query, top_k)
                generation_hits[:] = result.hits
                row["generation_query"] = query
                row["generation_rerank_status"] = result.rerank_status
                return result.hits

            rag = RAGService(traced_search, retriever.validate_hits, provider)
            history = [LLMMessage(**message) for message in case["history"]]
            async for event in rag.stream_answer(actor, kb_ids, case["question"], history):
                if event.type == "delta":
                    row["answer_text"] += event.payload["text"]
                elif event.type == "citations":
                    row["citations"] = event.payload["items"]
                elif event.type == "done":
                    row["answer_status"] = event.payload["answer_status"]
                    row["usage"] = event.payload.get("usage")
                elif event.type == "error":
                    row["error"] = event.payload["code"]
                    row["answer_status"] = "error"
            row["generation_hits"] = [hit.model_dump(mode="json") for hit in generation_hits]
            hit_map = {str(hit.chunk_id): hit for hit in generation_hits}
            for citation in row["citations"]:
                source_id = citation["source_id"]
                row["citation_sources"].append(source_map.get(stable_uuid(source_id), source_id))
                hit = hit_map.get(citation["chunk_id"])
                mapped = bool(
                    hit
                    and citation["source_id"] == str(hit.source_id)
                    and citation["quote"] in hit.text
                )
                row["citation_mapped"].append(mapped)
                if hit and not await retriever.validate_hits(actor, kb_ids, [hit]):
                    row["unauthorized_sources"].append(source_id)
            row["answer_term_coverage"] = (
                sum(term in row["answer_text"] for term in case["answer_terms"])
                / len(case["answer_terms"])
                if case["answer_terms"]
                else None
            )
            row["forbidden_answer_term_matches"] = [
                term
                for term in case.get("forbidden_answer_terms", [])
                if term in row["answer_text"]
            ]
    except Exception as exc:  # noqa: BLE001 - persist a safe failed sample, continue evaluation
        # Persist safe class/code only, never credentials, connection URLs or exception repr.
        row["error"] = getattr(exc, "code", type(exc).__name__)
        if provider is not None:
            row["answer_status"] = "error"
    row["latency_ms"] = (time.perf_counter() - started) * 1000
    return row


def stable_uuid(value):
    from uuid import UUID

    return UUID(value)


async def run_cases(dataset, split, factory, actor, kbs, retriever, provider):
    source_map = {stable_id(source["id"]): source["id"] for source in dataset["sources"]}
    rows = []
    for case in dataset["cases"]:
        if case["split"] == split:
            row = await evaluate_case(
                case,
                actor,
                [kbs[kb] for kb in case["allowed_kbs"]],
                retriever,
                source_map,
                provider,
            )
            rows.append(row)
            print(f"{case['id']}: {row['error'] or 'recorded'}", flush=True)
    return rows


def peak_memory():
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t)
                for name in [
                    "PeakWorkingSetSize",
                    "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage",
                    "PagefileUsage",
                    "PeakPagefileUsage",
                ]
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        memory_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if memory_info(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return counters.PeakWorkingSetSize
        return None
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def main():
    import yaml

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config_bytes = args.config.read_bytes()
    config = yaml.safe_load(config_bytes)
    dataset_path = ROOT / "experiments/evaluation/dataset.json"
    dataset = load_dataset(dataset_path)
    settings = Settings()
    embedder = BGEEmbedder(settings.embedding_model_path)
    load_started = time.perf_counter()
    embedder.load()
    embedding_load_ms = (time.perf_counter() - load_started) * 1000
    model_settings = ModelSettings()
    if args.generate and model_settings.model_provider != "ollama":
        raise ValueError(
            "generation requires explicitly configured local Ollama; Mock/cloud disallowed"
        )
    provider = create_provider(model_settings) if args.generate else None
    reranker = LocalCrossEncoder(settings.reranker_model_path) if config["rerank"] else None
    with evaluation_database() as factory:
        index_started = time.perf_counter()
        actor, kbs = build_index(factory, dataset, settings, embedder)
        indexing_ms = (time.perf_counter() - index_started) * 1000
        retriever = RetrievalService(
            factory,
            embedder,
            config["threshold"],
            mode=config["mode"],
            reranker=reranker,
            rerank_timeout=config["rerank_timeout_seconds"],
        )
        reranker_warmup_ms = None
        if reranker:
            warmup_case = next(case for case in dataset["cases"] if case["split"] == "dev")
            warmup_hits = asyncio.run(
                RetrievalService(factory, embedder, config["threshold"]).search(
                    actor,
                    [kbs[kb] for kb in warmup_case["allowed_kbs"]],
                    warmup_case["retrieval_query"],
                )
            )
            warmup_started = time.perf_counter()
            if warmup_hits:
                # Explicit evaluation warmup is outside per-query latency; request cold-load timeout
                # is separately covered by fallback tests. No final-test labels are consulted.
                reranker.rank(warmup_case["retrieval_query"], warmup_hits)
            reranker_warmup_ms = (time.perf_counter() - warmup_started) * 1000
        rows = asyncio.run(run_cases(dataset, args.split, factory, actor, kbs, retriever, provider))
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True))
    report = {
        "metadata": {
            "created_at": datetime.now(UTC).isoformat(),
            "dataset_version": dataset["version"],
            "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
            "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
            "config": config,
            "code_commit": commit,
            "working_tree_dirty": dirty,
            "split": args.split,
            "embedding_model": MODEL_ID,
            "embedding_revision": MODEL_REVISION,
            "embedding_device": "cpu",
            "embedding_load_ms": embedding_load_ms,
            "indexing_ms": indexing_ms,
            "reranker_warmup_ms": reranker_warmup_ms,
            "reranker_model": config.get("reranker_model") if reranker else None,
            "reranker_revision": config.get("reranker_revision") if reranker else None,
            "peak_process_working_set_bytes": peak_memory(),
            "prompt_version": PROMPT_VERSION,
            "provider": model_settings.model_provider if args.generate else None,
            "generation_model": model_settings.model_id if args.generate else None,
            "generation_randomness": (
                "RAG requests temperature=0; server determinism not guaranteed"
            ),
            "generation_enabled": args.generate,
            "python": platform.python_version(),
            "package_versions": {
                name: importlib.metadata.version(name)
                for name in [
                    "torch",
                    "sentence-transformers",
                    "transformers",
                    "sqlalchemy",
                ]
            },
            "synthetic": True,
            "human_reviewed": False,
            "limit": "教学样本；不代表真实业务、泛化能力或生产质量",
        },
        "summary": summarize(rows, k=5),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    return int(bool(report["summary"]["error_count"] or report["summary"]["permission_leaks"]))


if __name__ == "__main__":
    raise SystemExit(main())
