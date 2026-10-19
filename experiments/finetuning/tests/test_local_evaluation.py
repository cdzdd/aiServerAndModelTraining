import pytest
from experiments.evaluation.run_eval import select_generation_provider
from pydantic import SecretStr

from app.modules.providers.cloud import CloudProvider
from app.modules.providers.config import ModelSettings


def settings(url="http://127.0.0.1:11435/v1", provider="cloud"):
    return ModelSettings(
        _env_file=None,
        model_provider=provider,
        model_id="teaching-qwen",
        model_allowed_ids=["teaching-qwen"],
        model_api_key=SecretStr("a" * 32),
        model_base_url=url,
    )


def test_explicit_local_openai_only_selects_literal_loopback():
    assert isinstance(
        select_generation_provider(settings(), generate=True, local_openai=True), CloudProvider
    )
    assert select_generation_provider(settings(), generate=False, local_openai=False) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://remote.example/v1",
        "https://127.0.0.1/v1",
        "http://localhost:11435/v1",
        "https://host.docker.internal/v1",
    ],
)
def test_paid_or_dns_resolved_endpoints_are_rejected_before_inference(url):
    with pytest.raises(ValueError, match="loopback"):
        select_generation_provider(settings(url), generate=True, local_openai=True)


def test_opt_in_does_not_relax_normal_runner_or_allow_mock():
    with pytest.raises(ValueError, match="Ollama"):
        select_generation_provider(settings(), generate=True, local_openai=False)
    with pytest.raises(ValueError, match="cloud"):
        select_generation_provider(settings(provider="mock"), generate=True, local_openai=True)
    with pytest.raises(ValueError, match="generate"):
        select_generation_provider(settings(), generate=False, local_openai=True)


def test_runtime_manifest_requires_fixed_revision_and_sanitizes_metadata(tmp_path):
    import json

    from experiments.evaluation.run_eval import load_runtime_manifest

    path = tmp_path / "runtime.json"
    value = {
        "kind": "base",
        "base_revision": "cdbee75f17c01a7cc42f958dc650907174af0554",
        "inference_config_sha256": "a" * 64,
        "training_manifest_sha256": "b" * 64,
        "adapter_files_sha256": None,
        "runtime_versions": {"llamafactory": "0.9.5"},
        "private_key": "secret",
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    result = load_runtime_manifest(path)
    assert result["kind"] == "base"
    assert result["manifest_sha256"]
    assert "private_key" not in result
    value["base_revision"] = "unfixed"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="revision"):
        load_runtime_manifest(path)


@pytest.mark.parametrize(
    "kind,adapters",
    [
        ("base", {"adapter_model.safetensors": "a" * 64}),
        ("finetuned", {"adapter_model.safetensors": "not-a-sha256"}),
    ],
)
def test_runtime_manifest_does_not_mislabel_adapter_or_accept_invalid_hash(
    tmp_path, kind, adapters
):
    import json

    from experiments.evaluation.run_eval import load_runtime_manifest

    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps(
            {
                "kind": kind,
                "base_revision": "cdbee75f17c01a7cc42f958dc650907174af0554",
                "inference_config_sha256": "a" * 64,
                "training_manifest_sha256": "b" * 64,
                "adapter_files_sha256": adapters,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="adapter"):
        load_runtime_manifest(path)


@pytest.mark.parametrize(
    "adapters", [{"adapter_config.json": "a" * 64}, {"adapter_model.safetensors": "a" * 64}]
)
def test_finetuned_identity_requires_both_config_and_actual_weight_hash(tmp_path, adapters):
    import json

    from experiments.evaluation.run_eval import load_runtime_manifest

    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps(
            {
                "kind": "finetuned",
                "base_revision": "cdbee75f17c01a7cc42f958dc650907174af0554",
                "inference_config_sha256": "a" * 64,
                "training_manifest_sha256": "b" * 64,
                "adapter_files_sha256": adapters,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="adapter"):
        load_runtime_manifest(path)


def runtime_v2(kind="base"):
    import hashlib

    from app.modules.rag.prompts import ANSWER_SYSTEM, REWRITE_SYSTEM

    return {
        "schema_version": 2,
        "base_repository": "Qwen/Qwen3-8B",
        "base_revision": "b968826d9c46dd6066d109eabc6255188de91218",
        "kind": kind,
        "inference_config_sha256": "a" * 64,
        "training_manifest_sha256": "b" * 64,
        "training_data_sha256": "c" * 64,
        "prompt_sha256": {
            "answer": hashlib.sha256(ANSWER_SYSTEM.encode()).hexdigest(),
            "rewrite": hashlib.sha256(REWRITE_SYSTEM.encode()).hexdigest(),
            "general": "6ec8888abc33d084792f4a86c655ed0f51ca39dc8c78086348d401e1a444c6fe",
        },
        "files_sha256": dict.fromkeys(
            ["config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors"],
            "d" * 64,
        ),
        "adapter_files_sha256": None,
        "runtime_versions": {"torch": "2.9.1+cu128"},
        "generation_evidence": None,
    }


def write_runtime(tmp_path, value):
    import json

    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.mark.parametrize("kind", ["base", "lora", "full"])
def test_v2_requires_real_artifact_kind(tmp_path, kind):
    from experiments.evaluation.run_eval import load_runtime_manifest

    value = runtime_v2(kind)
    if kind == "lora":
        value["adapter_files_sha256"] = dict.fromkeys(
            ["adapter_config.json", "adapter_model.safetensors"], "e" * 64
        )
    value["private_key"] = "do-not-publish"
    value["model_path"] = "C:/private/model"
    value["runtime_versions"]["private_path"] = "C:/private/model"
    result = load_runtime_manifest(write_runtime(tmp_path, value))
    assert result["kind"] == kind
    assert result["training_data_sha256"] == "c" * 64
    assert "private_key" not in result and "model_path" not in result
    assert "private_path" not in result["runtime_versions"]


@pytest.mark.parametrize(
    "field,bad",
    [
        ("base_repository", "Qwen/Qwen3-4B"),
        ("base_revision", "latest"),
        ("training_data_sha256", None),
        ("files_sha256", {"adapter_model.safetensors": "d" * 64}),
        ("files_sha256", {"C:/model/config.json": "d" * 64}),
        ("generation_evidence", {"mode": "GREEDY_SEARCH", "do_sample": False}),
    ],
)
def test_v2_rejects_incomplete_or_unfixed_identity(tmp_path, field, bad):
    from experiments.evaluation.run_eval import load_runtime_manifest

    value = runtime_v2("full")
    value[field] = bad
    with pytest.raises(ValueError):
        load_runtime_manifest(write_runtime(tmp_path, value))


def test_v2_full_cannot_be_adapter_and_shards_must_be_complete(tmp_path):
    from experiments.evaluation.run_eval import load_runtime_manifest

    value = runtime_v2("full")
    value["adapter_files_sha256"] = {"adapter_config.json": "a" * 64}
    with pytest.raises(ValueError, match="adapter"):
        load_runtime_manifest(write_runtime(tmp_path, value))
    value["adapter_files_sha256"] = None
    del value["files_sha256"]["model.safetensors"]
    value["files_sha256"].update(
        {
            "model-00001-of-00002.safetensors": "a" * 64,
            "model.safetensors.index.json": "a" * 64,
        }
    )
    with pytest.raises(ValueError, match="files"):
        load_runtime_manifest(write_runtime(tmp_path, value))
    value["files_sha256"]["model-00002-of-00002.safetensors"] = "a" * 64
    assert load_runtime_manifest(write_runtime(tmp_path, value))["kind"] == "full"


def test_new_dataset_is_explicit_and_default_stays_legacy(tmp_path):
    import json

    from experiments.evaluation import run_eval

    loader = getattr(run_eval, "load_evaluation_dataset", None)
    assert callable(loader), "explicit evaluation dataset selection is missing"
    path = tmp_path / "original.json"
    path.write_text(
        json.dumps({"synthetic": True, "version": "fixture", "sources": [], "cases": []}),
        encoding="utf-8",
    )
    actual_path, dataset = loader(path)
    assert actual_path == path and dataset["version"] == "fixture"
    _, legacy = loader()
    assert len(legacy["cases"]) == 60


def test_full_identity_accepts_external_hf_chat_template_hash(tmp_path):
    from experiments.evaluation.run_eval import load_runtime_manifest

    value = runtime_v2("full")
    value["base_repository"] = "Qwen/Qwen3-0.6B"
    value["files_sha256"]["chat_template.jinja"] = "f" * 64
    result = load_runtime_manifest(write_runtime(tmp_path, value))
    assert result["files_sha256"]["chat_template.jinja"] == "f" * 64
    assert result["base_repository"] == "Qwen/Qwen3-0.6B"
    assert result["identity_assurance"] == "caller-verified artifacts; not server authentication"


@pytest.mark.parametrize(
    "name", ["../chat_template.jinja", "additional_chat_templates/default.jinja"]
)
def test_full_identity_rejects_template_paths_outside_supported_bare_files(tmp_path, name):
    from experiments.evaluation.run_eval import load_runtime_manifest

    value = runtime_v2("full")
    value["files_sha256"][name] = "f" * 64
    with pytest.raises(ValueError, match="bare"):
        load_runtime_manifest(write_runtime(tmp_path, value))


@pytest.mark.parametrize(
    "missing", ["config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors"]
)
def test_full_reload_requires_complete_config_tokenizer_and_weights(tmp_path, missing):
    from experiments.evaluation.run_eval import load_runtime_manifest

    value = runtime_v2("full")
    del value["files_sha256"][missing]
    with pytest.raises(ValueError, match="files"):
        load_runtime_manifest(write_runtime(tmp_path, value))


@pytest.mark.parametrize("adapter_location", ["adapter_files_sha256", "files_sha256"])
def test_full_identity_cannot_be_adapter(tmp_path, adapter_location):
    from experiments.evaluation.run_eval import load_runtime_manifest

    value = runtime_v2("full")
    value[adapter_location] = dict.fromkeys(
        ["adapter_config.json", "adapter_model.safetensors"], "e" * 64
    )
    with pytest.raises(ValueError):
        load_runtime_manifest(write_runtime(tmp_path, value))
