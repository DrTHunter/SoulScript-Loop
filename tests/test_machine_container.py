"""The reference machine as a real container: the walls that only exist when the server runs as root.

Skipped without Docker. CI has Docker, so these run there. They use the same fences as
machine/docker-compose.yml (capabilities dropped to what the server needs, no-new-privileges)."""

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="needs docker")
MACHINE = Path(__file__).parent.parent / "machine"
TOKEN = "container-test-token"


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


@pytest.fixture(scope="module")
def box():
    tag = "soulscript-machine-test"
    try:
        docker("info")
    except (subprocess.CalledProcessError, OSError):
        pytest.skip("docker daemon not running")
    docker("build", "-t", tag, str(MACHINE))
    name = f"{tag}-{int(time.time())}"
    docker("run", "-d", "--name", name, "-e", f"MACHINE_TOKEN={TOKEN}", "-p", "127.0.0.1::8080",
           "--cap-drop=ALL", *[f"--cap-add={c}" for c in ("CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID", "KILL")],
           "--security-opt", "no-new-privileges:true", tag)
    try:
        port = docker("port", name, "8080/tcp").stdout.strip().splitlines()[0].rsplit(":", 1)[1]
        url = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                urllib.request.urlopen(url + "/health", timeout=2)
                break
            except (urllib.error.URLError, OSError, ConnectionError):
                time.sleep(0.5)
        else:
            pytest.fail("machine never came up:\n" + docker("logs", name, check=False).stdout)
        yield url
    finally:
        docker("rm", "-f", name, check=False)


def call(url, path, body=None, token=TOKEN):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"http": e.code}


def sh(url, command, **kw):
    return call(url, "/exec", {"command": command, **kw})


def test_commands_run_as_the_unprivileged_agent(box):
    r = sh(box, "id -un; id -u; pwd")
    assert r["stdout"].split() == ["agent", "1000", "/home/agent"]
    assert ".machine-seeded" in sh(box, "ls -a ~")["stdout"]
    assert "This machine is yours" in sh(box, "cat ~/README.md")["stdout"]


def test_she_has_no_sudo_by_default(box):
    assert sh(box, "sudo -n true")["exit"] != 0


def test_she_cannot_read_the_token(box):
    env = sh(box, "env")["stdout"]
    assert TOKEN not in env and "MACHINE_TOKEN" not in env
    # the server is PID 1 (start.sh exec'd into it), a root process
    r = sh(box, "cat /proc/1/environ")
    assert r["exit"] != 0 and TOKEN not in r["stdout"]
    assert sh(box, "grep -rl " + TOKEN + " /proc/1 2>/dev/null; true")["stdout"].strip() == ""


def test_the_hud_is_hers_to_read_and_not_to_write(box):
    assert call(box, "/hud", {"tick": 3, "energy": 0.9, "hud_lines": ["FIELD · tick 3"]}) == {"ok": True, "tick": 3}
    assert json.loads(sh(box, "cat ~/hud/now.json")["stdout"])["tick"] == 3
    assert sh(box, "echo forged > ~/hud/now.json")["exit"] != 0
    assert sh(box, "touch /var/hud/new")["exit"] != 0
    assert sh(box, "rm -f ~/hud/now.json")["exit"] != 0
    # she can delete the pointer; what the loop writes is unaffected
    sh(box, "rm ~/hud && mkdir ~/hud && echo fake > ~/hud/now.json")
    call(box, "/hud", {"tick": 4, "hud_lines": []})
    assert json.loads(call(box, "/exec", {"command": "cat /var/hud/now.json"})["stdout"])["tick"] == 4


def test_the_command_log_is_root_owned_and_honest(box):
    sh(box, "echo marker-123")
    assert "marker-123" in call(box, "/log?lines=100")["text"]
    assert sh(box, "echo erased > /var/log/machine/shell.log")["exit"] != 0
    assert sh(box, "rm -f /var/log/machine/shell.log")["exit"] != 0


def test_a_runaway_is_killed_with_its_children(box):
    r = sh(box, "(sleep 60; touch ~/survived) & sleep 60", timeout=1)
    assert r["timed_out"] is True
    time.sleep(1)
    assert sh(box, "test -e ~/survived && echo yes || echo no")["stdout"].strip() == "no"
    assert sh(box, "pgrep -x sleep | wc -l")["stdout"].strip() == "0"


def test_a_symlink_out_of_her_home_does_not_leak(box):
    sh(box, "ln -sfn /etc/shadow ~/link && ln -sfn /etc ~/etclink")
    assert call(box, "/file?path=link").get("ok") is False
    assert call(box, "/file?path=etclink/passwd").get("ok") is False
    paths = {e["path"] for e in call(box, "/tree")["entries"]}
    assert "link" in paths and not any(p.startswith("etclink/") for p in paths)
