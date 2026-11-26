"""Read-only network/model preflight. No registered token is sent by this command."""

import asyncio
import json
import ssl
from pathlib import Path

import httpx2 as httpx

from app.modules.compute.desktop import BODY_LIMIT, NodeError, NodeParser, load_config


def _network_code(error, fallback):
    current = error
    while current is not None:
        if isinstance(current, ssl.SSLError):
            return "NODE_TLS_ERROR"
        current = current.__cause__
    return fallback


async def _probe(client, method, url):
    async with client.stream(method, url, json={} if method == "POST" else None) as response:
        raw = bytearray()
        async for part in response.aiter_bytes():
            raw.extend(part)
            if len(raw) > BODY_LIMIT:
                raise NodeError("NODE_BODY_LIMIT")
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            data = None
        return response.status_code, data


async def diagnose(config):
    checks = []
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10, connect=5), follow_redirects=False, trust_env=False
    ) as client:
        for name, method, url in (
            ("cloud_ready", "GET", config.cloud_url.rstrip("/") + "/health/ready"),
            ("compute_entry", "POST", config.cloud_url.rstrip("/") + "/internal/compute/claim"),
            ("ollama_version", "GET", config.model_base_url.rstrip("/") + "/api/version"),
            ("cached_model", "GET", config.model_base_url.rstrip("/") + "/api/tags"),
        ):
            status = None
            try:
                status, data = await _probe(client, method, url)
                if name == "compute_entry":
                    code = {
                        401: "NODE_ENTRY_REACHABLE",
                        403: "NODE_SOURCE_DENIED",
                        200: "NODE_AUTH_ENDPOINT_UNSAFE",
                        404: "NODE_CLOUD_ROUTE_MISSING",
                    }.get(status, "NODE_CLOUD_REFUSED")
                    ok = status == 401
                elif name == "cloud_ready":
                    ok = status == 200 and isinstance(data, dict) and data.get("status") == "ready"
                    code = "NODE_CLOUD_READY" if ok else "NODE_CLOUD_NOT_READY"
                elif name == "ollama_version":
                    ok = (
                        status == 200
                        and isinstance(data, dict)
                        and isinstance(data.get("version"), str)
                    )
                    code = "NODE_OLLAMA_READY" if ok else "NODE_OLLAMA_UNAVAILABLE"
                else:
                    models = data.get("models", []) if isinstance(data, dict) else []
                    ok = (
                        status == 200
                        and isinstance(models, list)
                        and any(
                            isinstance(model, dict) and model.get("name") == config.model_id
                            for model in models
                        )
                    )
                    code = "NODE_MODEL_CACHED" if ok else "NODE_MODEL_MISSING"
            except NodeError as error:
                ok, code = False, str(error)
            except httpx.HTTPError as error:
                ok = False
                code = _network_code(
                    error,
                    "NODE_CLOUD_UNREACHABLE"
                    if name.startswith(("cloud", "compute"))
                    else "NODE_OLLAMA_UNAVAILABLE",
                )
            entry = {"check": name, "ok": ok, "code": code}
            if status is not None:
                entry["http_status"] = status
            checks.append(entry)
    return {
        "ok": all(check["ok"] for check in checks),
        "model_id": config.model_id,
        "checks": checks,
    }


def main():
    parser = NodeParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = asyncio.run(diagnose(load_config(args.config)))
    except NodeError:
        report = {"ok": False, "checks": [{"check": "configuration", "code": "NODE_CONFIG_ERROR"}]}
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
