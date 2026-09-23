import asyncio
import importlib
import sys

import pytest


@pytest.fixture
def anyio_backend():
    if sys.platform == "win32":
        # Proactor server teardown can hang after a peer reset (WinError 10054).
        return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}
    return "asyncio"


@pytest.fixture
def provider_api():
    # Import inside a fixture so the RED run identifies the missing feature, not collection failure.
    try:
        return {
            name: importlib.import_module(f"app.modules.providers.{name}")
            for name in ("schemas", "cloud", "mock", "factory", "errors", "config")
        }
    except ModuleNotFoundError:
        pytest.fail("todo-004 provider implementation is missing", pytrace=False)


@pytest.fixture
def make_provider(provider_api):
    def make(url, **overrides):
        values = dict(
            model_provider="cloud",
            model_base_url=url,
            model_id="fake-model",
            model_api_key="fake-secret-never-log",
            model_allowed_ids=["fake-model"],
            model_connect_timeout_seconds=0.2,
            model_read_timeout_seconds=0.2,
        )
        values.update(overrides)
        settings = provider_api["config"].ModelSettings(_env_file=None, **values)
        return provider_api["factory"].create_provider(settings)

    return make


@pytest.fixture
def messages(provider_api):
    return [provider_api["schemas"].LLMMessage(role="user", content="你好")]
