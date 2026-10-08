"""Her own machine — bring your own Linux.

The loop ships the ``linux`` tool, not a machine. Point it at any server that
speaks this contract and she can run commands there; commands never run on the
host that runs the loop. Off unless ``machine.enabled`` is set with a ``url``. ``machine/`` in this repo is a
reference box that speaks it.

Optional, for a box that also speaks the HUD half (the reference one does): set ``hud_url``
and every tick's HUD is written to ``~/hud/`` on the machine, by a process she doesn't own, and
``~/hud-control.json`` (which she can write) steers her pace, rest and notes.

    POST {hud_url}/hud     a JSON object → 200 {"ok": true}
    GET  {url}/file?path=hud-control.json → 200 {"ok": true, "content": "…"}

    POST {url}/exec
    Authorization: Bearer <token>
    {"command": "bash command", "cwd": "", "timeout": 60}
    → 200 {"exit": int, "stdout": str, "stderr": str, "timed_out": bool, "cwd": str}

Anything else (401, timeouts, refused connections) comes back to her as an error.
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .registry import ToolRegistry

log = logging.getLogger(__name__)


class MachineTool:
    """The ``linux`` tool: one bash command per call, on her machine."""

    def __init__(self, url: str, token: str, max_timeout: int = 300, hud_url: str = ""):
        self.url = url.rstrip("/")
        self.token = token
        self.max_timeout = max_timeout
        self.hud_url = hud_url.rstrip("/")   # "" = no HUD: the reference machine serves it on a second port

    @staticmethod
    def definition() -> dict:
        return {
            "name": "linux",
            "description": (
                "Your own Linux machine. Runs one bash command and returns its exit code and output. "
                "Your home directory is a persistent disk — build there. Each call is a fresh shell: "
                "chain with && or pass cwd. Long-running things belong in tmux or nohup, not in one call. "
                "Whoever runs you can see every command."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "A bash command."},
                    "cwd": {"type": "string", "description": "Working directory (default: your home)."},
                    "timeout_seconds": {"type": "integer", "description": "Default 60, max 300."},
                },
                "required": ["command"],
            },
        }

    def execute(self, args: dict) -> str:
        command = (args.get("command") or "").strip()
        if not command:
            return "Error: command is required"
        timeout = max(1, min(self.max_timeout, int(args.get("timeout_seconds") or 60)))
        body = json.dumps({"command": command, "cwd": args.get("cwd") or "", "timeout": timeout}).encode()
        req = urllib.request.Request(f"{self.url}/exec", data=body, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout + 15) as resp:
                r = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return f"Error: the machine refused the command (HTTP {exc.code})"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return f"Error: can't reach your machine ({exc})"
        head = f"exit {r.get('exit')}" + (" · timed out" if r.get("timed_out") else "") + f" · {r.get('cwd', '')}"
        parts = [head]
        if r.get("stdout"):
            parts.append(r["stdout"].rstrip())
        if r.get("stderr"):
            parts.append("stderr:\n" + r["stderr"].rstrip())
        if len(parts) == 1:
            parts.append("(no output)")
        return "\n".join(parts)

    def _request(self, req: urllib.request.Request, timeout: float) -> dict:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    def read_file(self, path: str) -> dict:
        """One text file under her home (GET /file?path=…), for ~/hud-control.json."""
        req = urllib.request.Request(f"{self.url}/file?" + urllib.parse.urlencode({"path": path}),
                                     headers={"Authorization": f"Bearer {self.token}"})
        return self._request(req, 10)

    def push_hud(self, payload: dict) -> bool:
        """Write this tick's HUD into ~/hud/ on the machine. Best effort: a slow or down box never holds a tick."""
        if not self.hud_url:
            return False
        req = urllib.request.Request(f"{self.hud_url}/hud", data=json.dumps(payload, default=str).encode(),
                                     method="POST", headers={"Content-Type": "application/json",
                                                             "Authorization": f"Bearer {self.token}"})
        try:
            return self._request(req, 5).get("ok") is True
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return False

    def register(self, registry: ToolRegistry):
        registry.register(self.definition(), self.execute)


def machine_from_config(cfg: dict) -> Optional[MachineTool]:
    if not cfg.get("enabled"):
        return None
    url = cfg.get("url", "")
    token = os.environ.get(cfg.get("token_env", "LOOP_MACHINE_TOKEN"), "")
    if not url or not token:
        log.warning("[machine] enabled but url or token is missing — the linux tool is off")
        return None
    return MachineTool(url, token, hud_url=cfg.get("hud_url", ""))
