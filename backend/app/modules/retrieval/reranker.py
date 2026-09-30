"""Offline CPU cross-encoder adapter. It never downloads models during a request."""

import math
from pathlib import Path
from threading import Lock


class LocalCrossEncoder:
    def __init__(self, model_path: str):
        self.model_path = Path(model_path)
        self._model = None
        self._lock = Lock()

    def rank(self, query, hits):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("RERANK_BUSY")
        try:
            if not self.model_path.is_dir():
                raise RuntimeError("RERANK_UNAVAILABLE")
            if self._model is None:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(
                    str(self.model_path),
                    device="cpu",
                    local_files_only=True,
                    trust_remote_code=False,
                    max_length=512,
                )
            scores = self._model.predict(
                [(query, hit.title + "\n" + hit.text) for hit in hits],
                batch_size=8,
                show_progress_bar=False,
            )
            if len(scores) != len(hits) or not all(math.isfinite(float(score)) for score in scores):
                raise RuntimeError("RERANK_INVALID_OUTPUT")
            return [
                hit
                for _, hit in sorted(
                    zip(scores, hits, strict=True),
                    key=lambda item: (-float(item[0]), item[1].chunk_id),
                )
            ]
        finally:
            self._lock.release()
