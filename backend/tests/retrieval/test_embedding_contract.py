import hashlib
import importlib
import math

import pytest


class FakeTokenizer:
    def __call__(self, text, *, add_special_tokens, truncation):
        assert truncation is False
        count = len(text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", ""))
        return {"input_ids": list(range(count + (2 if add_special_tokens else 0)))}


class FakeModel:
    max_seq_length = 512
    device = "cpu"

    def __init__(self, vectors=None):
        self.tokenizer = FakeTokenizer()
        self.vectors = vectors
        self.inputs = []

    def get_sentence_embedding_dimension(self):
        return 512

    def encode(self, texts, **kwargs):
        self.inputs.extend(texts)
        assert kwargs["normalize_embeddings"] is True
        assert kwargs["batch_size"] == 16
        return self.vectors if self.vectors is not None else [[1.0] + [0.0] * 511 for _ in texts]


def embedder(monkeypatch, model=None):
    module = importlib.import_module("app.modules.retrieval.embedding")
    model = model or FakeModel()
    monkeypatch.setattr(module.BGEEmbedder, "_verify_model_files", lambda self: None)
    monkeypatch.setattr(module.BGEEmbedder, "_create_model", lambda self: model)
    return module.BGEEmbedder("unused"), model, module


def test_query_prefix_and_passage_plain_text(monkeypatch):
    encoder, model, module = embedder(monkeypatch)
    passage = encoder.encode_passages(["图书馆周末开放"])
    query = encoder.encode_query("周末能借书吗")
    assert model.inputs == ["图书馆周末开放", "为这个句子生成表示以用于检索相关文章：周末能借书吗"]
    assert len(passage) == 1 and len(passage[0]) == module.DIMENSION
    assert len(query) == module.DIMENSION
    assert math.isclose(math.dist(query, [0.0] * 512), 1.0)


@pytest.mark.parametrize("text", ["", "   "])
def test_blank_input_is_rejected(monkeypatch, text):
    encoder, _, module = embedder(monkeypatch)
    with pytest.raises(module.EmbeddingError) as error:
        encoder.encode_query(text)
    assert error.value.code == "INVALID_INPUT"


def test_token_limit_counts_query_prefix_and_special_tokens(monkeypatch):
    encoder, model, module = embedder(monkeypatch)
    # The fake tokenizer counts one token per character plus two special tokens.
    allowed = "x" * (512 - 2 - len(module.QUERY_PREFIX))
    assert len(encoder.encode_query(allowed)) == 512
    with pytest.raises(module.EmbeddingError) as error:
        encoder.encode_query(allowed + "x")
    assert error.value.code == "TOKEN_LIMIT"
    assert len(model.inputs) == 1


@pytest.mark.parametrize(
    "method,value", [("encode_query", "\u200b"), ("encode_passages", ["\u200b"])]
)
def test_zero_token_text_is_rejected_before_prefix(monkeypatch, method, value):
    encoder, model, module = embedder(monkeypatch)
    with pytest.raises(module.EmbeddingError) as error:
        getattr(encoder, method)(value)
    assert error.value.code == "INVALID_INPUT"
    assert model.inputs == []


@pytest.mark.parametrize(
    "vectors",
    [[], [[0.0] * 512], [[float("nan")] + [0.0] * 511], [[1.0]], [[2.0] + [0.0] * 511]],
)
def test_invalid_model_outputs_are_rejected(monkeypatch, vectors):
    encoder, _, module = embedder(monkeypatch, FakeModel(vectors))
    with pytest.raises(module.EmbeddingError) as error:
        encoder.encode_passages(["有效文本"])
    assert error.value.code == "INVALID_OUTPUT"


def test_local_cache_tampering_is_rejected_before_loading(monkeypatch, tmp_path):
    module = importlib.import_module("app.modules.retrieval.embedding")
    called = []
    monkeypatch.setattr(module.BGEEmbedder, "_create_model", lambda self: called.append(True))
    monkeypatch.setattr(
        module,
        "_MODEL_FILES",
        {"model.safetensors": hashlib.sha256(b"expected weights").hexdigest()},
    )
    (tmp_path / "model.safetensors").write_bytes(b"wrong weights")
    with pytest.raises(module.EmbeddingError) as error:
        module.BGEEmbedder(tmp_path).load()
    assert error.value.code == "MODEL_INTEGRITY"
    assert called == []
