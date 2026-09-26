"""Async internal search with fresh authorization after CPU embedding work."""

import asyncio
from functools import lru_cache
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import create_db_engine
from app.modules.auth.schemas import Actor
from app.modules.retrieval.embedding import BGEEmbedder
from app.modules.retrieval.repository import has_visible_scope, search_candidates
from app.modules.retrieval.schemas import RetrievalError, SearchHit


class RetrievalService:
    def __init__(self, session_factory, embedder, threshold: float = 0.65):
        self.session_factory = session_factory
        self.embedder = embedder
        self.threshold = threshold

    def _has_scope(self, actor, kb_ids):
        with self.session_factory() as db:
            return has_visible_scope(db, actor, kb_ids)

    def _search(self, actor, kb_ids, vector, top_k):
        with self.session_factory() as db:
            return search_candidates(
                db,
                actor,
                kb_ids,
                vector,
                top_k=top_k,
                threshold=self.threshold,
            )

    async def search(
        self,
        actor: Actor,
        kb_ids: list[UUID],
        query: str,
        top_k: int = 5,
    ) -> list[SearchHit]:
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
            return []
        vector = await asyncio.to_thread(self.embedder.encode_query, query)
        # This opens a new short session and applies the complete current SQL policy again.
        return await asyncio.to_thread(self._search, actor, requested_ids, vector, top_k)


@lru_cache(maxsize=1)
def get_retrieval_service() -> RetrievalService:
    settings = Settings()
    return RetrievalService(
        sessionmaker(bind=create_db_engine(settings), expire_on_commit=False),
        BGEEmbedder(settings.embedding_model_path),
        threshold=settings.retrieval_threshold,
    )


async def search(
    actor: Actor,
    kb_ids: list[UUID],
    query: str,
    top_k: int = 5,
) -> list[SearchHit]:
    return await get_retrieval_service().search(actor, kb_ids, query, top_k)
