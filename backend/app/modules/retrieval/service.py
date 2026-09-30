"""Async internal search with fresh authorization after CPU embedding work."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import create_db_engine
from app.modules.auth.schemas import Actor
from app.modules.retrieval.embedding import BGEEmbedder
from app.modules.retrieval.repository import has_visible_scope, search_candidates
from app.modules.retrieval.repository import validate_hits as validate_source_hits
from app.modules.retrieval.schemas import RetrievalError, SearchHit


@dataclass(frozen=True)
class SearchOutcome:
    hits: list[SearchHit]
    rerank_status: str = "disabled"


class RetrievalService:
    def __init__(
        self,
        session_factory,
        embedder,
        threshold: float = 0.65,
        *,
        mode="vector",
        reranker=None,
        rerank_timeout=2.0,
    ):
        if mode not in {"vector", "hybrid"}:
            raise ValueError("unknown retrieval mode")
        self.mode = mode
        self.reranker = reranker
        self.rerank_timeout = rerank_timeout
        self._rerank_executor = ThreadPoolExecutor(max_workers=1) if reranker else None
        self._rerank_slot = Lock()
        self.session_factory = session_factory
        self.embedder = embedder
        self.threshold = threshold

    def _has_scope(self, actor, kb_ids):
        with self.session_factory() as db:
            return has_visible_scope(db, actor, kb_ids)

    def _search(self, actor, kb_ids, vector, top_k, query=None):
        with self.session_factory() as db:
            return search_candidates(
                db,
                actor,
                kb_ids,
                vector,
                top_k=top_k,
                threshold=self.threshold,
                lexical_query=query,
            )

    def _validate_hits(self, actor, kb_ids, hits):
        with self.session_factory() as db:
            return validate_source_hits(db, actor, kb_ids, hits)

    async def validate_hits(self, actor: Actor, kb_ids: list[UUID], hits: list[SearchHit]) -> bool:
        # The generation phase holds no DB session; this session sees current permissions.
        return await asyncio.to_thread(self._validate_hits, actor, list(kb_ids), list(hits))

    async def search_detailed(
        self,
        actor: Actor,
        kb_ids: list[UUID],
        query: str,
        top_k: int = 5,
    ) -> SearchOutcome:
        if type(top_k) is not int or not 1 <= top_k <= 20:
            raise RetrievalError("INVALID_TOP_K")
        if not isinstance(query, str) or not query.strip() or "\0" in query:
            raise RetrievalError("INVALID_QUERY")
        try:
            query.encode("utf-8")
        except UnicodeEncodeError:
            raise RetrievalError("INVALID_QUERY") from None
        # Copy the caller's mutable scope before yielding. Never widen an empty scope.
        requested_ids = list(kb_ids)
        if not requested_ids or not await asyncio.to_thread(self._has_scope, actor, requested_ids):
            return SearchOutcome([])
        vector = await asyncio.to_thread(self.embedder.encode_query, query)
        # This opens a new short session and applies the complete current SQL policy again.
        candidate_k = 20 if self.mode == "hybrid" or self.reranker else top_k
        hits = await asyncio.to_thread(self._search, actor, requested_ids, vector, candidate_k)
        if self.mode == "hybrid":
            from app.modules.retrieval.hybrid import fuse

            lexical = await asyncio.to_thread(
                self._search, actor, requested_ids, vector, candidate_k, query
            )
            hits = fuse(hits, lexical, candidate_k)
        status = "disabled"
        if self.reranker and hits:
            if not await self.validate_hits(actor, requested_ids, hits):
                return SearchOutcome([], "source_changed")
            if not self._rerank_slot.acquire(blocking=False):
                status = "busy"
            else:
                future = self._rerank_executor.submit(self.reranker.rank, query, hits)
                future.add_done_callback(lambda completed: self._rerank_slot.release())
                try:
                    ranked = await asyncio.wait_for(
                        asyncio.wrap_future(future), self.rerank_timeout
                    )
                    originals = {hit.chunk_id: hit for hit in hits}
                    if (
                        len(ranked) != len(hits)
                        or len({hit.chunk_id for hit in ranked}) != len(hits)
                        or any(originals.get(hit.chunk_id) != hit for hit in ranked)
                    ):
                        raise ValueError("reranker changed candidates")
                    hits, status = ranked, "applied"
                except TimeoutError:
                    status = "timeout"
                except Exception:
                    status = "unavailable"
        hits = hits[:top_k]
        # Ranking may outlive membership or source changes. Never return stale text.
        if (
            (self.mode == "hybrid" or self.reranker)
            and hits
            and not await self.validate_hits(actor, requested_ids, hits)
        ):
            hits = []
        return SearchOutcome(hits, status)

    async def search(self, actor, kb_ids, query, top_k=5) -> list[SearchHit]:
        return (await self.search_detailed(actor, kb_ids, query, top_k)).hits


@lru_cache(maxsize=1)
def get_retrieval_service() -> RetrievalService:
    from app.modules.retrieval.reranker import LocalCrossEncoder

    settings = Settings()
    return RetrievalService(
        sessionmaker(bind=create_db_engine(settings), expire_on_commit=False),
        BGEEmbedder(settings.embedding_model_path),
        threshold=settings.retrieval_threshold,
        mode=settings.retrieval_mode,
        reranker=(
            LocalCrossEncoder(settings.reranker_model_path)
            if settings.retrieval_rerank_enabled
            else None
        ),
        rerank_timeout=settings.rerank_timeout_seconds,
    )


async def search(
    actor: Actor,
    kb_ids: list[UUID],
    query: str,
    top_k: int = 5,
) -> list[SearchHit]:
    return await get_retrieval_service().search(actor, kb_ids, query, top_k)


async def validate_hits(actor: Actor, kb_ids: list[UUID], hits: list[SearchHit]) -> bool:
    return await get_retrieval_service().validate_hits(actor, kb_ids, hits)
