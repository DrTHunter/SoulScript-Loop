import asyncio
import json

import pytest

from soulscript_loop import LoopConfig, LoopRunner
from soulscript_loop.sandbox import DockerSandbox, RunPythonTool

_probe = DockerSandbox.__new__(DockerSandbox)
_probe.docker = "docker"
DOCKER = _probe.available()
needs_docker = pytest.mark.skipif(not DOCKER, reason="Docker daemon not available")


def test_container_is_locked_down(tmp_path):
    cmd = DockerSandbox(tmp_path).base_command("x")
    joined = " ".join(cmd)
    for flag in [
        "--network none", "--read-only", "--cap-drop ALL",
        "--security-opt no-new-privileges", "--pids-limit 64",
    ]:
        assert flag in joined
    user = cmd[cmd.index("--user") + 1]
    assert not user.startswith("0:")
    mounts = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--mount"]
    assert mounts == [f"type=bind,src={tmp_path.resolve()},dst=/work"]


def test_cannot_run_files_outside_workbench(tmp_path):
    tool = RunPythonTool(DockerSandbox(tmp_path / "bench"))
    (tmp_path / "evil.py").write_text("print('host')")
    result = json.loads(asyncio.run(tool.execute({"path": "../evil.py"})))
    assert result["ok"] is False and "outside" in result["reason"]
    result = json.loads(asyncio.run(tool.execute({"path": "missing.py"})))
    assert result["ok"] is False


def test_sandbox_off_by_default(tmp_path):
    runner = LoopRunner(LoopConfig(data_dir=str(tmp_path)), backend=None)
    assert runner.sandbox is None
    assert "run_python" not in [t["function"]["name"] for t in runner.tools.definitions()]


def test_no_host_fallback_when_docker_missing(tmp_path):
    config = LoopConfig(data_dir=str(tmp_path), sandbox={"enabled": True, "docker": "definitely-not-docker"})
    runner = LoopRunner(config, backend=None)
    assert runner.sandbox is None
    assert "run_python" not in [t["function"]["name"] for t in runner.tools.definitions()]


@needs_docker
def test_runs_code_and_writes_to_workbench(tmp_path):
    sandbox = DockerSandbox(tmp_path)
    (tmp_path / "hello.py").write_text(
        "import sys\nopen('out.txt','w').write(sys.stdin.read().upper())\nprint('done')"
    )
    result = asyncio.run(sandbox.run_file("hello.py", stdin="hi"))
    assert result["exit_code"] == 0 and result["stdout"].strip() == "done"
    assert (tmp_path / "out.txt").read_text() == "HI"


@needs_docker
def test_no_network_and_timeout(tmp_path):
    sandbox = DockerSandbox(tmp_path, timeout_seconds=5)
    (tmp_path / "net.py").write_text(
        "import socket\nsocket.create_connection(('1.1.1.1', 53), timeout=2)"
    )
    assert asyncio.run(sandbox.run_file("net.py"))["exit_code"] != 0
    (tmp_path / "spin.py").write_text("while True: pass")
    assert asyncio.run(sandbox.run_file("spin.py"))["timed_out"] is True
