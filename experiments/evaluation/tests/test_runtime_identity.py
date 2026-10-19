import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PROMPT_HASHES = {
    "answer": "ac5eacabcc4e137eb6342136cb264d888ece446b7b43f87c862c397062f6e764",
    "rewrite": "8b5a526efe4648e071f5782c2aa2ae80ece40da2375cf03f5fa93500ab60a85b",
    "general": "6ec8888abc33d084792f4a86c655ed0f51ca39dc8c78086348d401e1a444c6fe",
}


def test_identity_import_works_with_database_provider_and_model_runtime_imports_blocked():
    probe = r"""
import importlib.abc
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path[:0] = [str(root), str(root / "backend")]
blocked = (
    "alembic", "sqlalchemy", "pydantic_settings", "fastapi", "torch", "transformers",
    "llamafactory", "accelerate", "peft", "bitsandbytes", "sentence_transformers",
    "app.core", "app.modules.auth", "app.modules.ingestion", "app.modules.knowledge",
    "app.modules.providers.factory", "app.modules.providers.config",
    "app.modules.retrieval.embedding", "app.modules.retrieval.indexing",
    "app.modules.retrieval.reranker", "app.modules.retrieval.service",
    "app.modules.rag.service",
)

def forbidden(name):
    return any(name == prefix or name.startswith(prefix + ".") for prefix in blocked)

class ImportBoundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if forbidden(fullname):
            raise AssertionError("heavy dependency imported: " + fullname)

sys.meta_path.insert(0, ImportBoundary())
from experiments.evaluation.runtime_identity import _model_files, prompt_hashes

files = dict.fromkeys(
    ("config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors"),
    "a" * 64,
)
assert _model_files(files) == files
assert not any(forbidden(name) for name in sys.modules)
print(json.dumps({"prompt_hashes": prompt_hashes(), "heavy_modules": []}, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", probe, str(ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"prompt_hashes": PROMPT_HASHES, "heavy_modules": []}


def test_prompt_identity_matches_production_prompts_and_existing_general_identity():
    import hashlib

    from experiments.evaluation.runtime_identity import GENERAL_SYSTEM, prompt_hashes

    from app.modules.rag.prompts import ANSWER_SYSTEM, REWRITE_SYSTEM

    assert prompt_hashes() == PROMPT_HASHES
    assert prompt_hashes() == {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for name, text in {
            "answer": ANSWER_SYSTEM,
            "rewrite": REWRITE_SYSTEM,
            "general": GENERAL_SYSTEM,
        }.items()
    }


@pytest.mark.parametrize(
    "value, valid",
    [
        ("0" * 64, True),
        ("abcdef12" * 8, True),
        ("A" * 64, False),
        ("a" * 63, False),
        ("a" * 64 + "\n", False),
        (None, False),
        (64, False),
    ],
)
def test_digest_requires_lowercase_sha256(value, valid):
    from experiments.evaluation.runtime_identity import _digest

    assert _digest(value) is valid


@pytest.fixture
def model_files():
    return dict.fromkeys(
        ["config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors"],
        "a" * 64,
    )


def test_model_files_accepts_unsharded_weights_and_known_optional_bare_files(model_files):
    from experiments.evaluation.runtime_identity import _model_files

    model_files.update(
        dict.fromkeys(
            [
                "generation_config.json",
                "tokenizer.model",
                "special_tokens_map.json",
                "added_tokens.json",
                "vocab.json",
                "merges.txt",
                "chat_template.jinja",
            ],
            "b" * 64,
        )
    )
    result = _model_files(model_files)
    assert result == model_files
    assert result is not model_files


def test_model_files_accepts_complete_shards_with_index(model_files):
    from experiments.evaluation.runtime_identity import _model_files

    del model_files["model.safetensors"]
    model_files.update(
        dict.fromkeys(
            [
                "model-00001-of-00002.safetensors",
                "model-00002-of-00002.safetensors",
                "model.safetensors.index.json",
            ],
            "c" * 64,
        )
    )
    assert _model_files(model_files) == model_files


@pytest.mark.parametrize("files", [None, [], "model.safetensors", {}])
def test_model_files_rejects_missing_file_mapping(files):
    from experiments.evaluation.runtime_identity import _model_files

    with pytest.raises(ValueError, match="actual model files"):
        _model_files(files)


@pytest.mark.parametrize(
    "missing",
    [
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "model.safetensors",
    ],
)
def test_model_files_rejects_missing_required_files(model_files, missing):
    from experiments.evaluation.runtime_identity import _model_files

    del model_files[missing]
    with pytest.raises(ValueError, match="files"):
        _model_files(model_files)


@pytest.mark.parametrize(
    "name,digest",
    [
        ("adapter_model.safetensors", "a" * 64),
        ("adapter_config.json", "a" * 64),
        ("../config.json", "a" * 64),
        ("C:/model/config.json", "a" * 64),
        ("additional_chat_templates/default.jinja", "a" * 64),
        ("unknown.json", "a" * 64),
        ("config.json", "A" * 64),
        ("config.json", "a" * 63),
        ("config.json", None),
        (1, "a" * 64),
    ],
)
def test_model_files_rejects_adapter_paths_unknown_names_and_invalid_hashes(
    model_files, name, digest
):
    from experiments.evaluation.runtime_identity import _model_files

    model_files[name] = digest
    with pytest.raises(ValueError, match="bare"):
        _model_files(model_files)


@pytest.mark.parametrize(
    "weights",
    [
        ["model.safetensors", "model.safetensors.index.json"],
        ["model.safetensors", "model-00001-of-00001.safetensors"],
        ["model-00001-of-00002.safetensors", "model.safetensors.index.json"],
        ["model-00001-of-00001.safetensors"],
        [
            "model-00001-of-00002.safetensors",
            "model-00002-of-00003.safetensors",
            "model.safetensors.index.json",
        ],
    ],
)
def test_model_files_rejects_mixed_or_incomplete_weight_sets(model_files, weights):
    from experiments.evaluation.runtime_identity import _model_files

    del model_files["model.safetensors"]
    model_files.update(dict.fromkeys(weights, "d" * 64))
    with pytest.raises(ValueError, match="model files"):
        _model_files(model_files)


def test_run_eval_reexports_the_shared_identity_symbols():
    from experiments.evaluation import run_eval, runtime_identity

    for name in ("GENERAL_SYSTEM", "prompt_hashes", "_digest", "_model_files"):
        assert getattr(run_eval, name) is getattr(runtime_identity, name)
