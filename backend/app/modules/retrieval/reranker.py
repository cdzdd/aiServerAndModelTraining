"""Offline CPU cross-encoder adapter. It never downloads models during a request."""

import hashlib
import math
from pathlib import Path
from threading import Lock

MODEL_ID = "BAAI/bge-reranker-base"
MODEL_REVISION = "2cfc18c9415c912f9d8155881c133215df768a70"
MODEL_FILES = {
    "config.json": "289adf7ada1eb6b4afa7589a48a032d45a076cf2e46dcdb3b4cabc33be14f708",
    "model.safetensors": "ced967c45fd1902eb92716c9ceeca7c95a936770ea9db611f5a841b926e33fbd",
    "sentencepiece.bpe.model": "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
    "special_tokens_map.json": "d5469a60db23249c7f8945013d78df30b44b6bf686c6bb4740f4223f77b1b535",
    "tokenizer_config.json": "a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b",
    "tokenizer.json": "9eb652ac4e40cc093272bbbe0f55d521cf67570060227109b5cdc20945a4489e",
}


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
                try:
                    for name, expected in MODEL_FILES.items():
                        with (self.model_path / name).open("rb") as stream:
                            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                                raise RuntimeError("RERANK_INTEGRITY")
                except OSError:
                    raise RuntimeError("RERANK_INTEGRITY") from None
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
