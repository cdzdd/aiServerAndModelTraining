import pytest
from pydantic import ValidationError

from app.modules.providers.config import ModelSettings
from app.modules.providers.factory import create_provider


def settings(provider="ollama", **overrides):
    values = dict(
        model_provider=provider,
        model_base_url="http://127.0.0.1:11434",
        model_id="local-model",
        model_allowed_ids=["local-model"],
        model_api_key="",
    )
    values.update(overrides)
    return ModelSettings(_env_file=None, **values)


@pytest.mark.parametrize(
    "provider,expected",
    [
        ("mock", "MockProvider"),
        ("cloud", "CloudProvider"),
        ("ollama", "OllamaProvider"),
    ],
)
def test_explicit_provider_selection(provider, expected):
    config = settings(provider, model_api_key="cloud-key" if provider == "cloud" else "")
    assert type(create_provider(config)).__name__ == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_provider": "auto"},
        {"model_allowed_ids": []},
        {"model_id": "other"},
        {"model_base_url": "http://public.example"},
        {"model_base_url": "https://user:secret@internal.example"},
        {"model_base_url": "https://internal.example?key=secret"},
        {"model_base_url": "https://internal.example#secret"},
        {"ollama_num_ctx": 0},
        {"ollama_num_ctx": 131073},
    ],
)
def test_invalid_ollama_configuration_is_rejected(overrides):
    with pytest.raises(ValidationError) as error:
        settings(**overrides)
    assert "key=secret" not in str(error.value)


def test_no_api_key_needed_for_local_ollama():
    assert type(create_provider(settings())).__name__ == "OllamaProvider"


def test_cloud_still_requires_key():
    with pytest.raises(ValidationError):
        settings("cloud")


def test_ollama_allows_explicit_docker_host_http_only():
    config = settings(model_base_url="http://host.docker.internal:11434")
    assert type(create_provider(config)).__name__ == "OllamaProvider"
    with pytest.raises(ValidationError):
        settings("cloud", model_base_url="http://host.docker.internal:11434", model_api_key="key")
