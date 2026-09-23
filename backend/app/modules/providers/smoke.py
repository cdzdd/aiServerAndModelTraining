"""Explicit, one-request cloud smoke. Never called by the application or test runner."""

import argparse
import asyncio
import json
from contextlib import aclosing
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic import ValidationError
from pydantic_settings.exceptions import SettingsError

from .config import ModelSettings
from .errors import ProviderError
from .factory import create_provider
from .schemas import LLMMessage


async def run_smoke(settings: ModelSettings) -> dict:
    if settings.model_provider != "cloud":
        raise ProviderError("PROVIDER_CONFIG_ERROR")
    started = perf_counter()
    characters = 0
    final = None
    async with aclosing(
        create_provider(settings).stream(
            [LLMMessage(role="user", content="请用中文简短回答：1加1等于几？")],
            max_tokens=min(64, settings.model_max_output_tokens),
            temperature=0,
        )
    ) as stream:
        async for delta in stream:
            characters += len(delta.text)
            if delta.finish_reason:
                final = delta
    return {
        "model": settings.model_id,
        "date": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(perf_counter() - started, 3),
        "text_characters": characters,
        "finish_reason": final.finish_reason,
        "usage": final.usage.model_dump() if final.usage else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One explicit cloud call, at most 64 output tokens."
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--run", action="store_true", help="Send one billable request; no retries.")
    args = parser.parse_args()
    if not args.run:
        print(
            "No request sent. Check the provider, call budget and configuration before using --run."
        )
        return 0
    if not args.env_file.is_file():
        print("PROVIDER_CONFIG_ERROR: configuration file not found")
        return 1
    try:
        settings = ModelSettings(_env_file=args.env_file)
        summary = asyncio.run(run_smoke(settings))
    except (ValidationError, SettingsError):
        print("PROVIDER_CONFIG_ERROR: check model configuration")
        return 1
    except ProviderError as error:
        print(error.code + ": " + error.message)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["finish_reason"] == "stop" else 1


if __name__ == "__main__":
    raise SystemExit(main())
