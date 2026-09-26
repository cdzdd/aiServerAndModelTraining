"""Pinned, offline BGE embeddings for indexed passages and queries."""

import hashlib
import math
from pathlib import Path
from threading import RLock

MODEL_ID = "BAAI/bge-small-zh-v1.5"
MODEL_REVISION = "7999e1d3359715c523056ef9478215996d62a620"
DIMENSION = 512
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

# SHA-256 values of the official fixed-revision snapshot, including every file
# that affects tokenization, model architecture, pooling, or vector weights.
_MODEL_FILES = {
    "1_Pooling/config.json": "aaa8861589f80c961a03cc86c7eeaef7605c1676b9ab55329d33a304738769c6",
    "config_sentence_transformers.json": (
        "940d5f50db195fa6e5e6a4f122c095f77880de259d74b14a65779ed48bdd7c56"
    ),
    "config.json": "3853a7979202c348751b753e36f579c41d8da7d36af617d3d907e1fc9b441f2a",
    "model.safetensors": "354763b9b1357bc9c44f62c6be2276321081ed2567773608c0d0785b61d5a026",
    "modules.json": "84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf",
    "sentence_bert_config.json": "84e39fda68ccbff05bfa723ae9c0e70e23e2ec373b76e0f8c6e71af72a693cbf",
    "special_tokens_map.json": "b6d346be366a7d1d48332dbc9fdf3bf8960b5d879522b7799ddba59e76237ee3",
    "tokenizer_config.json": "e6f3b96db926a37d4039995fbf5ad17de158dfb8f6343d607e4dbaad18d75f5a",
    "tokenizer.json": "48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26",
    "vocab.txt": "45bbac6b341c319adc98a532532882e91a9cefc0329aa57bac9ae761c27b291c",
}


class EmbeddingError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class BGEEmbedder:
    def __init__(self, model_path: str | Path):
        self.model_path = Path(model_path)
        self._model = None
        self._lock = RLock()

    def _verify_model_files(self) -> None:
        try:
            for name, expected in _MODEL_FILES.items():
                with (self.model_path / name).open("rb") as source:
                    if hashlib.file_digest(source, "sha256").hexdigest() != expected:
                        raise EmbeddingError("MODEL_INTEGRITY")
        except OSError as exc:
            raise EmbeddingError("MODEL_INTEGRITY") from exc

    def _create_model(self):
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(
            str(self.model_path), device="cpu", local_files_only=True, trust_remote_code=False
        )

    def load(self) -> "BGEEmbedder":
        with self._lock:
            if self._model is None:
                self._verify_model_files()
                try:
                    model = self._create_model()
                    if (
                        model.get_sentence_embedding_dimension() != DIMENSION
                        or model.max_seq_length != 512
                        or str(model.device) != "cpu"
                        or model.tokenizer is None
                    ):
                        raise EmbeddingError("MODEL_INTEGRITY")
                except EmbeddingError:
                    raise
                except Exception as exc:
                    raise EmbeddingError("MODEL_UNAVAILABLE") from exc
                self._model = model
        return self

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not isinstance(texts, list) or any(
            not isinstance(value, str) or not value.strip() for value in texts
        ):
            raise EmbeddingError("INVALID_INPUT")
        if not texts:
            return []

        self.load()
        with self._lock:
            tokenizer = self._model.tokenizer
            try:
                for value in texts:
                    raw = tokenizer(value, add_special_tokens=False, truncation=False)["input_ids"]
                    full = tokenizer(value, add_special_tokens=True, truncation=False)["input_ids"]
                    if not raw:
                        raise EmbeddingError("INVALID_INPUT")
                    if len(full) > 512:
                        raise EmbeddingError("TOKEN_LIMIT")
            except EmbeddingError:
                raise
            except Exception as exc:
                raise EmbeddingError("MODEL_UNAVAILABLE") from exc

            try:
                encoded = self._model.encode(
                    texts,
                    batch_size=16,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
            except Exception as exc:
                raise EmbeddingError("ENCODE_FAILED") from exc

        try:
            if len(encoded) != len(texts):
                raise EmbeddingError("INVALID_OUTPUT")
            vectors = []
            for row in encoded:
                vector = [float(value) for value in row]
                if len(vector) != DIMENSION or not all(math.isfinite(value) for value in vector):
                    raise EmbeddingError("INVALID_OUTPUT")
                norm = math.sqrt(math.fsum(value * value for value in vector))
                if not 0.999 <= norm <= 1.001:
                    raise EmbeddingError("INVALID_OUTPUT")
                vectors.append(vector)
            return vectors
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError("INVALID_OUTPUT") from exc

    def encode_passages(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def encode_query(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingError("INVALID_INPUT")
        self.load()
        with self._lock:
            try:
                raw = self._model.tokenizer(
                    text, add_special_tokens=False, truncation=False
                )["input_ids"]
            except Exception as exc:
                raise EmbeddingError("MODEL_UNAVAILABLE") from exc
        if not raw:
            raise EmbeddingError("INVALID_INPUT")
        return self._encode([QUERY_PREFIX + text])[0]
