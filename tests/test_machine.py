import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from soulscript_loop import EchoBackend, HashEmbedder, LoopConfig, build_loop
from soulscript_loop.machine import MachineTool, machine_from_config


class FakeMachine(BaseHTTPRequestHandler):
    """Speaks the /exec contract with canned answers. Never runs anything."""

    seen = []

    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer secret":
            self.send_response(401)
            self.end_headers()
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeMachine.seen.append(body)
        reply = {"exit": 3, "stdout": "hi\n", "stderr": "oops\n", "timed_out": body["timeout"] == 1, "cwd": "/home/her"}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def machine():
    server = HTTPServer(("127.0.0.1", 0), FakeMachine)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    FakeMachine.seen = []
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def tool_names(daemon):
    return [t["function"]["name"] for t in daemon.host.tools.definitions()]


def test_machine_off_by_default(tmp_path):
    daemon = build_loop(LoopConfig(data_dir=str(tmp_path)), backend=EchoBackend(), embedder=HashEmbedder())
    assert "linux" not in tool_names(daemon)


def test_machine_needs_url_and_token(monkeypatch):
    monkeypatch.delenv("LOOP_MACHINE_TOKEN", raising=False)
    assert machine_from_config({"enabled": True, "url": "http://x"}) is None
    monkeypatch.setenv("LOOP_MACHINE_TOKEN", "t")
    assert machine_from_config({"enabled": True, "url": ""}) is None
    assert machine_from_config({"enabled": False, "url": "http://x"}) is None
    assert isinstance(machine_from_config({"enabled": True, "url": "http://x"}), MachineTool)


def test_enabled_machine_offers_linux_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOP_MACHINE_TOKEN", "t")
    cfg = LoopConfig(data_dir=str(tmp_path), machine={"enabled": True, "url": "http://127.0.0.1:1"})
    daemon = build_loop(cfg, backend=EchoBackend(), embedder=HashEmbedder())
    assert "linux" in tool_names(daemon)


def test_sends_the_contract_and_formats_the_reply(machine):
    out = MachineTool(machine, "secret").execute({"command": "echo hi", "cwd": "src", "timeout_seconds": 999})
    assert FakeMachine.seen == [{"command": "echo hi", "cwd": "src", "timeout": 300}]
    assert out == "exit 3 · /home/her\nhi\nstderr:\noops"


def test_timeouts_are_reported(machine):
    assert "timed out" in MachineTool(machine, "secret").execute({"command": "sleep 5", "timeout_seconds": 1})


def test_wrong_token_is_refused(machine):
    assert "HTTP 401" in MachineTool(machine, "wrong").execute({"command": "echo hi"})


def test_unreachable_or_empty_is_an_error_not_a_crash():
    assert MachineTool("http://127.0.0.1:1", "t").execute({"command": "ls"}).startswith("Error: can't reach")
    assert MachineTool("http://127.0.0.1:1", "t").execute({"command": "  "}) == "Error: command is required"
