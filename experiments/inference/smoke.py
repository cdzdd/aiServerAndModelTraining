"""Explicit local-model smoke; three fixed requests, never an implicit cloud call."""

import argparse
import asyncio
import json
import sys
from contextlib import aclosing
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import httpx2 as httpx
from pydantic import ValidationError
from pydantic_settings.exceptions import SettingsError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.modules.providers.config import ModelSettings  # noqa: E402
from app.modules.providers.errors import ProviderError  # noqa: E402
from app.modules.providers.factory import create_provider  # noqa: E402
from app.modules.providers.schemas import LLMMessage  # noqa: E402


async def run_smoke(settings: ModelSettings, *, label="uncontrolled") -> dict:
    if settings.model_provider != "ollama":
        raise ProviderError("PROVIDER_CONFIG_ERROR")
    cases = []
    for name, question in (
        ("short_first", "请只用一个数字回答：1加1等于几？"),
        ("short_second", "请只用一个数字回答：3加4等于几？"),
        ("short_third", "请只用一个数字回答：1加1等于几？"),
    ):
        started = perf_counter()
        record = {
            "name": name,
            "question": question,
            "text": "",
            "first_text_seconds": None,
            "finish_reason": None,
            "usage": None,
            "error_code": None,
        }
        try:
            async with aclosing(
                create_provider(settings).stream(
                    [LLMMessage(role="user", content=question)],
                    max_tokens=min(64, settings.model_max_output_tokens),
                    temperature=0,
                )
            ) as stream:
                async for delta in stream:
                    if delta.text and record["first_text_seconds"] is None:
                        record["first_text_seconds"] = perf_counter() - started
                    record["text"] += delta.text
                    if delta.finish_reason:
                        record["finish_reason"] = delta.finish_reason
                        record["usage"] = delta.usage.model_dump() if delta.usage else None
        except ProviderError as error:
            record["error_code"] = error.code
        record["elapsed_seconds"] = perf_counter() - started
        cases.append(record)
    return {
        "utc": datetime.now(UTC).isoformat(),
        "provider": "ollama",
        "model": settings.model_id,
        "num_ctx": settings.ollama_num_ctx,
        "max_output_tokens": min(64, settings.model_max_output_tokens),
        "first_request_state": label,
        "planned_requests": 3,
        "successes": sum(case["finish_reason"] == "stop" for case in cases),
        "cases": cases,
        "vram_peak_mib": None,
    }


async def metadata(settings):
    # Metadata contains no endpoint, credentials or arbitrary server error response.
    async with httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False) as client:
        base = settings.model_base_url.rstrip("/")
        version = await client.get(base + "/api/version")
        tags = await client.get(base + "/api/tags")
        version.raise_for_status()
        tags.raise_for_status()
        selected = next((m for m in tags.json()["models"] if m["name"] == settings.model_id), None)
        return {
            "ollama_version": version.json()["version"],
            "model_digest": selected.get("digest") if selected else None,
            "model_details": selected.get("details") if selected else None,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run three explicit local Ollama requests.")
    parser.add_argument("--provider", choices=["ollama"], default="ollama")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--output", type=Path, default=ROOT / ".local/ollama-smoke.json")
    parser.add_argument("--label", choices=["cold", "warm", "uncontrolled"], default="uncontrolled")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args(argv)
    if not args.run:
        print("No model request sent. Use --run after checking the local model and environment.")
        return 0
    try:
        settings = ModelSettings(_env_file=args.env_file, model_provider=args.provider)
        model_metadata = asyncio.run(metadata(settings))
        report = asyncio.run(run_smoke(settings, label=args.label))
    except (ValidationError, SettingsError, OSError):
        print("PROVIDER_CONFIG_ERROR: check the local configuration")
        return 1
    except (httpx.HTTPError, ValueError, TypeError, KeyError, StopIteration):
        print("PROVIDER_UNAVAILABLE: local model metadata is unavailable")
        return 1
    except ProviderError as error:
        print(error.code + ": " + error.message)
        return 1
    report.update(model_metadata)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"successes": report["successes"], "requests": 3, "report": str(args.output)}))
    return 0 if report["successes"] == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
