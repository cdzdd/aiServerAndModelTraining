import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("pwsh"), reason="Windows script")
def test_windows_script_preflights_starts_one_owned_node_and_stops_it(tmp_path):
    script = Path(__file__).resolve().parents[3] / "scripts/compute-node/node.ps1"
    secret = "fixture-secret-not-for-console"
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, data):
            raw = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/health/ready":
                self.respond(200, {"status": "ready"})
            elif self.path == "/api/version":
                self.respond(200, {"version": "fixture"})
            elif self.path == "/api/tags":
                self.respond(200, {"models": [{"name": "fixture-model"}]})
            else:
                self.respond(404, {})

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append((self.path, self.headers.get("Authorization")))
            if self.path != "/internal/compute/claim":
                self.respond(404, {})
            elif self.headers.get("Authorization") == "Bearer " + secret:
                self.respond(200, {"job": None})
            else:
                self.respond(401, {})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    config = tmp_path / "formal config.json"
    config.write_text(json.dumps({
        "cloud_url": url, "model_base_url": url, "model_id": "fixture-model", "token": secret,
    }))
    environment = dict(os.environ)

    def run(action, *, success=True, tag=""):
        # Background Windows children can inherit pipe handles; files let us wait on
        # the foreground PowerShell process without waiting for the node's lifetime.
        with (tmp_path / (action + tag + ".out")).open("w+", encoding="utf-8") as output:
            with (tmp_path / (action + tag + ".err")).open("w+", encoding="utf-8") as error:
                process = subprocess.run(
                    ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(script),
                     "-Action", action, "-ConfigPath", str(config)],
                    stdout=output, stderr=error, text=True, timeout=30, env=environment,
                )
                output.seek(0)
                error.seek(0)
                out, err = output.read(), error.read()
        assert secret not in out + err
        if success is None:
            return process.returncode, out, err
        assert (process.returncode == 0) == success, out + err
        return out

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            launches = [
                pool.submit(run, "start", success=None, tag=str(i)) for i in range(2)
            ]
            results = [task.result() for task in launches]
        assert sorted(code for code, _, _ in results) == [0, 1]
        assert "NODE_PROCESS_STARTED" in next(out for code, out, _ in results if code == 0)
        receipt = json.loads(Path(str(config) + ".process.json").read_text())
        # A live supervisor may still be waiting for the Python wrapper on a slow host.
        for _ in range(30):
            state = json.loads(run("status"))
            if state["MatchingPythonProcesses"]:
                break
            time.sleep(.1)
        assert state["ProcessRunning"] and state["MatchingPythonProcesses"] in {1, 2}
        assert state["SupervisorPID"] == receipt["PID"]
        assert state["CloudOnlineConfirmed"] is False
        run("start", success=False)
        assert json.loads(Path(str(config) + ".process.json").read_text()) == receipt
        assert any(auth == "Bearer " + secret for _, auth in calls)
        assert "NODE_STOPPED_CHECK_MODEL_IDLE" in run("stop")
        assert json.loads(run("status"))["ProcessRunning"] is False
        assert json.loads(run("status"))["MatchingPythonProcesses"] == 0
    finally:
        run("stop")
        server.shutdown()
        server.server_close()

