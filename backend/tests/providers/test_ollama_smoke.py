import importlib.util
from pathlib import Path

import pytest

from . import test_ollama as ollama_tests
from .fixtures.cloud_events import cloud_server

frame = ollama_tests.frame
make_ollama = ollama_tests.make_ollama

pytestmark = pytest.mark.anyio


def load_smoke():
    path = Path(__file__).resolve().parents[3] / "experiments/inference/smoke.py"
    if not path.is_file():
        pytest.fail("todo-014 real inference smoke entry is missing", pytrace=False)
    spec = importlib.util.spec_from_file_location("inference_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_smoke_records_fixed_three_requests_and_actual_usage(make_ollama):
    smoke_api = load_smoke()
    async with cloud_server(
        [frame("2", done=True, reason="stop", prompt_eval_count=5, eval_count=1)],
        content_type="application/x-ndjson",
    ) as (url, requests, _):
        report = await smoke_api.run_smoke(make_ollama(url).settings)
    assert report["planned_requests"] == 3
    assert report["successes"] == 3
    assert len(requests) == 3
    assert report["vram_peak_mib"] is None
    assert all(case["first_text_seconds"] >= 0 for case in report["cases"])
    assert all(case["elapsed_seconds"] >= case["first_text_seconds"] for case in report["cases"])
    assert report["cases"][0]["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 1,
        "total_tokens": None,
    }


async def test_smoke_records_sanitized_failures_without_extra_retry(make_ollama):
    smoke_api = load_smoke()
    async with cloud_server([b"private-host.local secret body"], status=404) as (url, requests, _):
        report = await smoke_api.run_smoke(make_ollama(url).settings)
    assert report["successes"] == 0
    assert len(requests) == 3
    assert all(case["error_code"] == "PROVIDER_UNAVAILABLE" for case in report["cases"])
    assert "private-host" not in str(report)
    assert "secret body" not in str(report)
