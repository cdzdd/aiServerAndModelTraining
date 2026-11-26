import json
import ssl

import httpx2 as httpx
import pytest

from app.modules.compute.desktop import DesktopConfig

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def config():
    return DesktopConfig(
        cloud_url="https://qa.example",
        token="doctor-secret-must-stay-private",
        model_id="exact-model",
        model_base_url="http://127.0.0.1:11434",
    )


def install_transport(monkeypatch, doctor, handler):
    original = httpx.AsyncClient
    options = []

    def client(**kwargs):
        options.append(kwargs)
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(doctor.httpx, "AsyncClient", client)
    return options


async def test_doctor_probes_without_credentials_and_requires_exact_cached_model(
    config, monkeypatch
):
    from app.modules.compute import doctor

    requests = []

    def handle(request):
        requests.append(request)
        assert "authorization" not in request.headers
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ready"})
        if request.url.path == "/internal/compute/claim":
            assert request.method == "POST" and json.loads(request.content) == {}
            return httpx.Response(401, json={"error": "not authenticated"})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.35.0"})
        return httpx.Response(200, json={"models": [{"name": config.model_id}]})

    options = install_transport(monkeypatch, doctor, handle)
    report = await doctor.diagnose(config)
    assert report["ok"]
    assert len(requests) == 4
    assert all(o["trust_env"] is False and o["follow_redirects"] is False for o in options)
    assert all(o.get("verify", True) is not False for o in options)
    assert config.token not in json.dumps(report)


@pytest.mark.parametrize(
    "status,expected", [(403, "NODE_SOURCE_DENIED"), (200, "NODE_AUTH_ENDPOINT_UNSAFE")]
)
async def test_doctor_reports_gateway_rejection_or_unprotected_route(
    config, monkeypatch, status, expected
):
    from app.modules.compute import doctor

    def handle(request):
        if request.url.path == "/internal/compute/claim":
            return httpx.Response(status, text=config.token)
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ready"})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.35.0"})
        return httpx.Response(200, json={"models": [{"name": config.model_id}]})

    install_transport(monkeypatch, doctor, handle)
    report = await doctor.diagnose(config)
    assert not report["ok"]
    assert next(c for c in report["checks"] if c["check"] == "compute_entry")["code"] == expected
    assert config.token not in json.dumps(report)


@pytest.mark.parametrize("tls", [False, True])
async def test_doctor_does_not_hide_network_error_or_download_missing_model(
    config, monkeypatch, tls
):
    from app.modules.compute import doctor

    paths = []

    def handle(request):
        paths.append(request.url.path)
        if request.url.scheme == "https":
            if not tls:
                raise httpx.ReadTimeout(config.token, request=request)
            try:
                raise ssl.SSLCertVerificationError("certificate details are private")
            except ssl.SSLCertVerificationError as cause:
                raise httpx.ConnectError(config.token, request=request) from cause
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.35.0"})
        return httpx.Response(200, json={"models": [{"name": "another-model"}]})

    install_transport(monkeypatch, doctor, handle)
    report = await doctor.diagnose(config)
    codes = {c["code"] for c in report["checks"]}
    expected = "NODE_TLS_ERROR" if tls else "NODE_CLOUD_UNREACHABLE"
    assert not report["ok"] and expected in codes and "NODE_MODEL_MISSING" in codes
    assert "/api/pull" not in paths and "/api/generate" not in paths
    assert config.token not in json.dumps(report)
