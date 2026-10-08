"""The reference machine (machine/server.py), run for real on localhost against a temp home.

These run unprivileged, so they check the protocol, the clipping, the time limits, the symlink refusal
and the token hygiene. The root-only walls (dropping to the agent user, the sealed HUD folder) are
exercised by the container test in CI."""

import importlib.util
import json
import shutil
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from soulscript_loop.machine import MachineTool

pytestmark = pytest.mark.skipif(not shutil.which("bash") or sys.platform == "win32" and not shutil.which("bash"),
                                reason="needs bash")
TOKEN = "t0ken-for-tests"


@pytest.fixture()
def box(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("MACHINE_TOKEN", TOKEN)
    monkeypatch.setenv("AGENT_HOME", str(home))
    monkeypatch.setenv("MACHINE_LOG", str(tmp_path / "log" / "shell.log"))
    monkeypatch.setenv("MACHINE_HUD_DIR", str(tmp_path / "hud"))
    spec = importlib.util.spec_from_file_location("machine_server", Path(__file__).parent.parent / "machine" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mod.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield mod, url, home, tmp_path
    srv.shutdown()


def call(url, path, body=None, token=TOKEN):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_everything_but_health_needs_the_token(box):
    mod, url, home, _ = box
    assert call(url, "/health", token=None) == (200, {"ok": True})
    for path, body in (("/exec", {"command": "echo hi"}), ("/hud", {}), ("/log", None), ("/tree", None), ("/stats", None)):
        assert call(url, path, body, token=None)[0] == 401, path
        assert call(url, path, body, token="wrong")[0] == 401, path


def test_exec_runs_logs_and_reports_exit_codes(box):
    mod, url, home, tmp = box
    code, r = call(url, "/exec", {"command": "echo out; echo err >&2; exit 3"})
    assert code == 200 and r["exit"] == 3 and r["stdout"].strip() == "out" and r["stderr"].strip() == "err"
    assert r["timed_out"] is False and Path(r["cwd"]) == home
    (home / "sub").mkdir()
    assert Path(call(url, "/exec", {"command": "pwd", "cwd": str(home / "sub")})[1]["cwd"]) == home / "sub"
    log = call(url, "/log?lines=50")[1]["text"]
    assert "$ echo out; echo err >&2; exit 3" in log and "[exit 3]" in log
    assert (tmp / "log" / "shell.log").exists()
    assert call(url, "/exec", {"command": ""})[0] == 400


def test_commands_cannot_see_the_token(box):
    _, url, *_ = box
    r = call(url, "/exec", {"command": "env; cat /proc/$PPID/environ 2>/dev/null | tr '\\0' '\\n'"})[1]
    assert TOKEN not in r["stdout"] and "MACHINE_TOKEN" not in r["stdout"]


def test_a_runaway_command_is_killed_with_its_children(box):
    _, url, home, _ = box
    r = call(url, "/exec", {"command": "(sleep 30; touch survived) & sleep 30", "timeout": 1})[1]
    assert r["timed_out"] is True and r["exit"] == -1
    import time
    time.sleep(0.5)
    assert not (home / "survived").exists()


def test_output_is_clipped_to_the_tail(box):
    mod, url, *_ = box
    r = call(url, "/exec", {"command": "seq 1 60000"})[1]
    assert len(r["stdout"]) < mod.MAX_OUTPUT + 200 and "cut" in r["stdout"] and r["stdout"].rstrip().endswith("60000")


def test_files_are_readable_only_inside_her_home(box):
    _, url, home, tmp = box
    (home / "notes.md").write_text("hello", encoding="utf-8")
    (tmp / "secret.txt").write_text("outside", encoding="utf-8")
    assert call(url, "/file?path=notes.md")[1]["content"] == "hello"
    assert call(url, "/file?path=../secret.txt")[1] == {"ok": False, "reason": "outside her home"}
    try:
        (home / "link").symlink_to(tmp / "secret.txt")
    except OSError:
        pytest.skip("cannot create symlinks here")
    assert call(url, "/file?path=link")[1]["ok"] is False
    tree = {e["path"] for e in call(url, "/tree")[1]["entries"]}
    assert "notes.md" in tree


def test_the_hud_is_written_atomically_and_trimmed(box):
    mod, url, _, tmp = box
    code, r = call(url, "/hud", {"tick": 7, "energy": 0.5, "hud_lines": ["FIELD · tick 7", "⚡ 50%"]})
    assert code == 200 and r == {"ok": True, "tick": 7}
    hud = tmp / "hud"
    assert json.loads((hud / "now.json").read_text(encoding="utf-8"))["tick"] == 7
    assert (hud / "now.txt").read_text(encoding="utf-8").splitlines() == ["FIELD · tick 7", "⚡ 50%"]
    assert "hud-control.json" in (hud / "README.md").read_text(encoding="utf-8")
    assert not list(hud.glob(".*.tmp"))
    mod.HUD_LOG_MAX = 2000
    for i in range(100):
        call(url, "/hud", {"tick": i, "pad": "x" * 100})
    lines = (hud / "log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) < 100 and json.loads(lines[-1])["tick"] == 99
    assert all(json.loads(l) for l in lines)                            # trimmed on a whole line


def test_the_loops_machine_client_speaks_to_it(box):
    _, url, home, tmp = box
    tool = MachineTool(url, TOKEN, hud_url=url)
    out = tool.execute({"command": "echo from the loop"})
    assert out.startswith("exit 0") and "from the loop" in out
    assert tool.push_hud({"tick": 1, "hud_lines": ["a"]}) is True
    (home / "hud-control.json").write_text('{"seq": 2}', encoding="utf-8")
    assert json.loads(tool.read_file("hud-control.json")["content"]) == {"seq": 2}
    assert MachineTool(url, "bad", hud_url=url).push_hud({"tick": 1}) is False
    assert MachineTool(url, TOKEN).push_hud({"tick": 1}) is False        # no hud_url → off
