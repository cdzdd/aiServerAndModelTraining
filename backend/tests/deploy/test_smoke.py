import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

spec = importlib.util.spec_from_file_location(
    "runtime_smoke", Path(__file__).resolve().parents[3] / "scripts/deploy/smoke.py"
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


@pytest.fixture
def server():
    responses = {
        "/health/live": (200, "application/json", b'{"status":"ok"}'),
        "/health/ready": (200, "application/json", b'{"status":"ready"}'),
        "/login": (200, "text/html", b'<div id="app"></div>'),
        "/chat/test-deep-link": (200, "text/html", b'<div id="app"></div>'),
        "/admin/users": (200, "text/html", b'<div id="app"></div>'),
        "/api/v1/runtime-missing": (404, "application/json", b'{"error":{"code":"NOT_FOUND"}}'),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            code, content_type, body = responses[self.path]
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", responses
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def test_probe_accepts_healthy_same_origin_routes(server):
    url, _ = server
    smoke.probe(url)


def test_probe_rejects_spa_fallback_swallowing_api(server):
    url, responses = server
    responses["/api/v1/runtime-missing"] = (200, "text/html", b'<div id="app"></div>')
    with pytest.raises(smoke.SmokeError):
        smoke.probe(url)


def test_probe_does_not_treat_liveness_as_readiness(server):
    url, responses = server
    responses["/health/ready"] = (503, "application/json", b'{"status":"unavailable"}')
    with pytest.raises(smoke.SmokeError):
        smoke.probe(url)
