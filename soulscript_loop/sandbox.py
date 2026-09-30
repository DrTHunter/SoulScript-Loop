"""Sandbox — runs the Python she writes inside a locked-down Docker container.

There is no host fallback. If Docker isn't available, the run_python tool
is simply not offered. Every run gets:

  * no network (``--network none``)
  * CPU, memory, and process-count limits
  * a read-only root filesystem, all capabilities dropped, no privilege escalation
  * an unprivileged user (nobody)
  * a wall-clock timeout, after which the container is killed

The only mount is the workbench at ``/work`` (read-write, so code can
build on her files). Nothing else from the host is visible.
"""

import asyncio
import json
import logging
import subprocess
import uuid
from pathlib import Path
from typing import List, Optional

from .tools import ToolRegistry

log = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 20_000


class DockerSandbox:
    def __init__(
        self,
        workdir: str | Path,
        image: str = "python:3.12-slim",
        timeout_seconds: float = 30.0,
        memory: str = "256m",
        cpus: str = "0.5",
        pids_limit: int = 64,
        docker: str = "docker",
    ):
        self.workdir = Path(workdir).resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.image = image
        self.timeout = timeout_seconds
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.docker = docker

    def available(self) -> bool:
        try:
            result = subprocess.run(
                [self.docker, "version", "--format", "{{.Server.Version}}"],
                capture_output=True, text=True, timeout=15,
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def base_command(self, name: str) -> List[str]:
        return [
            self.docker, "run", "--rm", "-i",
            "--name", name,
            "--network", "none",
            "--memory", self.memory,
            "--memory-swap", self.memory,
            "--cpus", self.cpus,
            "--pids-limit", str(self.pids_limit),
            "--read-only",
            "--tmpfs", "/tmp:rw,size=64m",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", "65534:65534",
            "--mount", f"type=bind,src={self.workdir},dst=/work",
            "--workdir", "/work",
            "--env", "PYTHONDONTWRITEBYTECODE=1",
            self.image,
        ]

    async def _run(self, argv: List[str], stdin: str = "") -> dict:
        name = f"soulscript-loop-{uuid.uuid4().hex[:12]}"
        proc = await asyncio.create_subprocess_exec(
            *self.base_command(name), *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timed_out = False
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin.encode()), timeout=self.timeout)
        except asyncio.TimeoutError:
            timed_out = True
            kill = await asyncio.create_subprocess_exec(
                self.docker, "kill", name,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await kill.wait()
            out, err = await proc.communicate()
        return {
            "exit_code": None if timed_out else proc.returncode,
            "timed_out": timed_out,
            "stdout": out.decode("utf-8", errors="replace")[-MAX_OUTPUT_CHARS:],
            "stderr": err.decode("utf-8", errors="replace")[-MAX_OUTPUT_CHARS:],
        }

    async def run_file(self, rel_path: str, stdin: str = "") -> dict:
        """Run a .py file from the workbench (path relative to the workbench root)."""
        path = (self.workdir / rel_path).resolve()
        if self.workdir not in path.parents:
            raise PermissionError(f"'{rel_path}' is outside the workbench")
        if not path.is_file():
            raise FileNotFoundError(f"No such file: {rel_path}")
        return await self._run(["python", "-I", path.relative_to(self.workdir).as_posix()], stdin)


class RunPythonTool:
    """Lets her execute a script from her workbench — inside the sandbox, never on the host."""

    def __init__(self, sandbox: DockerSandbox):
        self.sandbox = sandbox

    @staticmethod
    def definition() -> dict:
        return {
            "name": "run_python",
            "description": (
                "Run a Python file from your workbench inside an isolated sandbox "
                "(no network, limited CPU/memory/time, standard library only). "
                "Your workbench is the working directory, so the script can read and "
                "write your files. Returns exit code, stdout, and stderr."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workbench path of the .py file, e.g. 'drafts/parser.py'."},
                    "stdin": {"type": "string", "description": "Optional text piped to the script's stdin."},
                },
                "required": ["path"],
            },
        }

    async def execute(self, args: dict) -> str:
        try:
            result = await self.sandbox.run_file(args.get("path", ""), args.get("stdin", ""))
        except (PermissionError, FileNotFoundError) as exc:
            return json.dumps({"ok": False, "reason": str(exc)})
        return json.dumps(result, indent=2)

    def register(self, registry: ToolRegistry):
        registry.register(self.definition(), self.execute)


def sandbox_from_config(cfg: dict, workdir: Path) -> Optional[DockerSandbox]:
    opts = {k: v for k, v in cfg.items() if k != "enabled"}
    sandbox = DockerSandbox(workdir, **opts)
    if not sandbox.available():
        log.warning("[sandbox] Docker is not available — run_python is disabled")
        return None
    return sandbox
