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
