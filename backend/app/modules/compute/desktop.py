"""Serial, outbound-only Ollama worker. Run with --config PATH [--once]."""

import argparse
import asyncio
import json
import sys
from contextlib import aclosing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx2 as httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.modules.providers.config import ModelSettings
from app.modules.providers.errors import ProviderError
from app.modules.providers.ollama import OllamaProvider
from app.modules.providers.schemas import LLMMessage

BODY_LIMIT = 65536


class NodeError(Exception):
    """Only fixed diagnostic codes cross the CLI boundary."""


class DesktopConfig(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)
    cloud_url: str
    token: str = Field(repr=False, min_length=1)
    model_id: str = Field(min_length=1)
    model_base_url: str
    ollama_num_ctx: int = Field(default=4096, ge=512, le=131072)

    @model_validator(mode="after")
    def validate_private_config(self):
        for value, local_only in ((self.cloud_url, False), (self.model_base_url, True)):
            parsed = urlsplit(value)
            _ = parsed.port
            loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            if (
                not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.path not in ("", "/")
                or any(ord(char) <= 32 for char in value)
                or (local_only and (parsed.scheme != "http" or not loopback))
                or (
                    not local_only
                    and not (parsed.scheme == "https" or (parsed.scheme == "http" and loopback))
                )
            ):
                raise ValueError("invalid worker destination")
        if (
            not self.model_id.strip()
            or any(ord(char) < 32 for char in self.model_id)
            or any(ord(char) < 33 or ord(char) > 126 for char in self.token)
        ):
            raise ValueError("invalid worker identity")
        return self


def load_config(path: Path) -> DesktopConfig:
    try:
        with path.open("rb") as source:
            raw = source.read(BODY_LIMIT + 1)
        if len(raw) > BODY_LIMIT:
            raise NodeError("NODE_CONFIG_ERROR")
        return DesktopConfig.model_validate_json(raw)
    except (OSError, ValueError, ValidationError, RecursionError):
        raise NodeError("NODE_CONFIG_ERROR") from None


class _Payload(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)
    model_id: str
    messages: list[LLMMessage] = Field(min_length=1)
    max_tokens: int = Field(ge=1, le=512)
    temperature: float = Field(ge=0, le=2, allow_inf_nan=False)


class _Claim(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)
    job_id: str
    lease_token: str = Field(min_length=1, max_length=512, repr=False)
    deadline: str
    payload: _Payload


async def _request(client, path, body, *, status=204):
    raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > BODY_LIMIT:
        raise NodeError("NODE_BODY_LIMIT")
    try:
        async with client.stream("POST", path, content=raw) as response:
            if response.status_code != status:
                raise NodeError("NODE_CLOUD_REFUSED")
            data = bytearray()
            async for part in response.aiter_raw():
                data.extend(part)
                if len(data) > BODY_LIMIT:
                    raise NodeError("NODE_BODY_LIMIT")
        return json.loads(data) if status == 200 else None
    except (httpx.HTTPError, ValueError, RecursionError):
        raise NodeError("NODE_CLOUD_ERROR") from None


async def _generate(provider, payload):
    text = ""
    try:
        async with aclosing(
            provider.stream(
                payload.messages, max_tokens=payload.max_tokens, temperature=payload.temperature
            )
        ) as stream:
            async for delta in stream:
                text += delta.text
                if len(text) > 8192:
                    raise ProviderError("PROVIDER_PROTOCOL_ERROR")
                if delta.finish_reason:
                    return {
                        "model_id": payload.model_id,
                        "text": text,
                        "finish_reason": delta.finish_reason,
                        "usage": delta.usage.model_dump() if delta.usage else None,
                    }
        raise ProviderError("PROVIDER_STREAM_INTERRUPTED")
    except ProviderError as error:
        return {"error_code": error.code}


async def _execute(client, provider, job, claimed_at):
    loop = asyncio.get_running_loop()
    remaining = (datetime.fromisoformat(job.deadline) - datetime.now(UTC)).total_seconds()
    deadline = min(loop.time() + remaining, claimed_at + 60)
    lease_until = claimed_at + 15
    base = f"/internal/compute/{UUID(job.job_id)}"

    async def heartbeat():
        nonlocal lease_until
        while True:
            try:
                async with asyncio.timeout_at(min(deadline, lease_until)):
                    await asyncio.sleep(5)
                    sent_at = loop.time()
                    await _request(client, base + "/heartbeat", {"lease_token": job.lease_token})
                lease_until = sent_at + 15
            except TimeoutError:
                raise NodeError("NODE_DEADLINE_OR_LEASE_EXPIRED") from None

    if min(deadline, lease_until) <= loop.time():
        raise NodeError("NODE_DEADLINE_OR_LEASE_EXPIRED")
    generation = asyncio.create_task(_generate(provider, job.payload))
    pulse = asyncio.create_task(heartbeat())
    try:
        done, _ = await asyncio.wait((generation, pulse), return_when=asyncio.FIRST_COMPLETED)
        if pulse in done:
            await pulse
        result = await generation
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)
        if not pulse.cancelled():
            await pulse
        try:
            async with asyncio.timeout_at(min(deadline, lease_until)):
                await _request(
                    client,
                    base + "/result",
                    {
                        "lease_token": job.lease_token,
                        "result": result,
                    },
                )
        except TimeoutError:
            raise NodeError("NODE_DEADLINE_OR_LEASE_EXPIRED") from None
        if "error_code" in result:
            # Closing a failed stream is not evidence that the GPU has stopped.
            raise NodeError("NODE_GENERATION_FAILED")
    finally:
        for task in (generation, pulse):
            task.cancel()
        await asyncio.gather(generation, pulse, return_exceptions=True)


async def run_node(config: DesktopConfig, *, once=False):
    provider = OllamaProvider(
        ModelSettings(
            _env_file=None,
            model_provider="ollama",
            model_base_url=config.model_base_url,
            model_id=config.model_id,
            model_allowed_ids=[config.model_id],
            model_api_key="",
            model_disable_thinking=False,
            model_connect_timeout_seconds=10,
            model_read_timeout_seconds=60,
            model_max_output_tokens=512,
            ollama_num_ctx=config.ollama_num_ctx,
        )
    )
    async with httpx.AsyncClient(
        base_url=config.cloud_url.rstrip("/"),
        timeout=httpx.Timeout(10),
        follow_redirects=False,
        trust_env=False,
        headers={
            "Authorization": f"Bearer {config.token}",
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
            "Cache-Control": "no-store",
        },
    ) as client:
        while True:
            claimed_at = asyncio.get_running_loop().time()
            envelope = await _request(client, "/internal/compute/claim", {}, status=200)
            try:
                if not isinstance(envelope, dict) or set(envelope) != {"job"}:
                    raise ValueError
                if envelope["job"] is not None:
                    job = _Claim.model_validate(envelope["job"])
                    UUID(job.job_id)
                    deadline = datetime.fromisoformat(job.deadline)
                    if (
                        deadline.tzinfo is None
                        or job.payload.model_id != config.model_id
                        or sum(len(m.content.encode("utf-8")) for m in job.payload.messages) > 12000
                    ):
                        raise ValueError
                else:
                    job = None
            except (ValueError, TypeError, ValidationError, OverflowError):
                raise NodeError("NODE_INVALID_JOB") from None
            if job is not None:
                await _execute(client, provider, job, claimed_at)
            if once:
                return
            await asyncio.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run_node(load_config(args.config), once=args.once))
    except NodeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
