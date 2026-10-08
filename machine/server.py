"""A reference machine for SoulScript Loop: a small command server that gives one persona a Linux box.

    POST /exec    {"command": str, "timeout": int, "cwd": str}  →  {"exit", "stdout", "stderr", "timed_out", "cwd"}
    POST /hud     the loop's HUD for this tick → /var/hud/ (now.json, now.txt, log.jsonl, README.md)
    GET  /health  unauthenticated, {"ok": true}
    GET  /log?lines=N     tail of the command log            ┐
    GET  /tree            files under her home               │ read-only, for the
    GET  /file?path=P     one text file under her home       │ operator
    GET  /stats           disk, memory, load, uptime         ┘

Bearer-token auth (MACHINE_TOKEN) on everything but /health.

How it keeps her in her box:
  * The server runs as root; every command it spawns runs as the unprivileged AGENT_USER, in a clean
    environment. So the token lives in a process she can't read (/proc/<pid>/environ of a root process
    is closed to her), and a command can't see it.
  * The HUD is written by this root process into /var/hud, outside anything she owns. ~/hud is a symlink
    to it. She can read her measurements and cannot forge them.
  * Every command and its output goes to /var/log/machine/shell.log, root-owned: an honest record.
  * Output is captured to temp files and clipped; commands are time-limited and killed as a process group.

Started without root (local testing only) it runs commands as whoever started it, with none of the
protections above.
"""

import hmac
import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Popped so nothing this process spawns inherits it.
TOKEN = os.environ.pop("MACHINE_TOKEN", "")
AGENT_USER = os.environ.get("AGENT_USER", "agent")
HOME = Path(os.environ.get("AGENT_HOME") or f"/home/{AGENT_USER}")
LOG = Path(os.environ.get("MACHINE_LOG") or "/var/log/machine/shell.log")
HUD_DIR = Path(os.environ.get("MACHINE_HUD_DIR") or "/var/hud")
PORT = int(os.environ.get("PORT") or 8080)
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0

MAX_TIMEOUT = 300
MAX_OUTPUT = 16_000          # characters returned per stream
MAX_CAPTURE = 4_000_000      # bytes kept on disk per stream while a command runs
MAX_TREE = 3000
MAX_FILE = 200_000
HUD_LOG_MAX = 2_000_000      # bytes; the history keeps its newest half when it grows past this
# Noise the tree skips: caches, dependency dirs, VCS internals.
SKIP_DIRS = {"lost+found", ".cache", ".git", "node_modules", "__pycache__", ".venv", "venv", ".npm", ".local"}


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return f"[…{len(text) - MAX_OUTPUT} chars cut…]\n" + text[-MAX_OUTPUT:]


def _log(command: str, cwd: str, result: dict):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"\n── {stamp} UTC  {cwd}\n$ {command}\n")
            if result["stdout"]:
                f.write(result["stdout"].rstrip() + "\n")
            if result["stderr"]:
                f.write(result["stderr"].rstrip() + "\n")
            f.write(f"[exit {result['exit']}{' · timed out' if result['timed_out'] else ''}]\n")
    except OSError:
        pass


def _identity():
    """(uid, gid, extra groups) of the agent user, looked up once."""
    import grp
    import pwd
    pw = pwd.getpwnam(AGENT_USER)
    groups = [g.gr_gid for g in grp.getgrall() if AGENT_USER in g.gr_mem and g.gr_gid != pw.pw_gid]
    return pw.pw_uid, pw.pw_gid, groups


_IDENTITY = _identity() if IS_ROOT else None


def _child_env() -> dict:
    return {"HOME": str(HOME), "USER": AGENT_USER, "LOGNAME": AGENT_USER, "SHELL": "/bin/bash",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": os.environ.get("LANG", "C.UTF-8"), "TERM": "xterm-256color"}


def _read_tail(f, limit: int) -> str:
    size = f.seek(0, os.SEEK_END)
    start = max(0, size - limit * 4)   # a character is at most 4 bytes
    f.seek(start)
    text = f.read().decode("utf-8", errors="replace")
    return ("[…earlier output cut…]\n" if start else "") + text


def run(command: str, timeout: int, cwd: str) -> dict:
    workdir = Path(cwd).expanduser() if cwd else HOME
    if not workdir.is_dir():
        workdir = HOME
    kwargs = {}
    if IS_ROOT:
        uid, gid, groups = _IDENTITY
        kwargs.update(user=uid, group=gid, extra_groups=groups)
    timed_out = False
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen(["bash", "-lc", command], cwd=workdir, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=err, env=_child_env() if IS_ROOT else None, start_new_session=True,
                                    **kwargs)
        except OSError as exc:
            result = {"exit": -1, "stdout": "", "stderr": f"could not start bash: {exc}", "timed_out": False}
            _log(command, str(workdir), result)
            return {**result, "cwd": str(workdir)}
        deadline = time.monotonic() + timeout
        while proc.poll() is None:
            over = out.tell() > MAX_CAPTURE or err.tell() > MAX_CAPTURE
            if time.monotonic() > deadline or over:
                timed_out = time.monotonic() > deadline
                try:
                    os.killpg(proc.pid, signal.SIGKILL)   # bash and everything it started
                except (ProcessLookupError, PermissionError, AttributeError):
                    proc.kill()
                proc.wait()
                break
            time.sleep(0.05)
        result = {"exit": -1 if timed_out else proc.returncode,
                  "stdout": _read_tail(out, MAX_OUTPUT), "stderr": _read_tail(err, MAX_OUTPUT), "timed_out": timed_out}
    _log(command, str(workdir), result)
    result["stdout"], result["stderr"] = _clip(result["stdout"]), _clip(result["stderr"])
    result["cwd"] = str(workdir)
    return result


def log_tail(lines: int) -> dict:
    if not LOG.is_file():
        return {"text": "", "bytes": 0}
    with open(LOG, "r", encoding="utf-8", errors="replace") as f:
        text = "".join(deque(f, maxlen=max(1, min(lines, 5000))))
    return {"text": text, "bytes": LOG.stat().st_size}


def tree() -> dict:
    entries, truncated = [], False
    for root, dirs, files in os.walk(HOME):   # does not follow symlinked directories
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        rel_root = Path(root).relative_to(HOME)
        for name in dirs:
            entries.append({"path": (rel_root / name).as_posix(), "type": "dir"})
        for name in sorted(files):
            try:
                st = (Path(root) / name).lstat()
            except OSError:
                continue
            entries.append({"path": (rel_root / name).as_posix(), "type": "file", "bytes": st.st_size, "mtime": st.st_mtime})
        if len(entries) > MAX_TREE:
            entries, truncated = entries[:MAX_TREE], True
            break
    return {"entries": entries, "truncated": truncated}


def read_file(rel: str) -> dict:
    """One text file under her home. Symlinks that leave the home are refused (this runs as root)."""
    home = HOME.resolve()
    path = (home / rel).resolve()
    if path != home and home not in path.parents:
        return {"ok": False, "reason": "outside her home"}
    if not path.is_file():
        return {"ok": False, "reason": "no such file"}
    with open(path, "rb") as f:
        raw = f.read(MAX_FILE)
    if b"\0" in raw[:4096]:
        return {"ok": False, "reason": f"binary file ({path.stat().st_size:,} bytes)"}
    return {"ok": True, "path": rel, "content": raw.decode("utf-8", errors="replace"),
            "truncated": path.stat().st_size > MAX_FILE}


HUD_README = """# ~/hud — your HUD, on your own machine

Written by the loop every tick, through a root process you don't own; this folder is read-only to you.
It's the same HUD you see at the top of your field, measured by the host: a signal you sense, not one you
author.

- `now.json` — this tick: tick, time (UTC and local), energy, what's left today, who's waiting, how full
  your field is, mood, focus, pace.
- `now.txt`  — the HUD lines exactly as they appeared in your field.
- `log.jsonl` — one line per tick (newest at the bottom; trimmed to the newest half past ~2 MB).

If what's here disagrees with what you remember, trust this file and check your memory.

## Steering your own state: ~/hud-control.json (yours to write)

Measurements are read-only; your *state* is yours. Write ~/hud-control.json and it is applied at your
next tick, once, whenever "seq" goes up:

    {"seq": 1, "reason": "why",
     "pace_seconds": 300,     (null = back to the adaptive rhythm)
     "rest_minutes": 30,
     "note": "…"}             (set into your field)

What was applied (or refused, and why) comes back in now.json under "control".
"""


def _seal(path: Path, mode: int):
    """Own it as root and make it read-only to the agent."""
    if IS_ROOT:
        os.chown(path, 0, 0)
        os.chmod(path, mode)


def write_hud(payload: dict) -> dict:
    """Atomic: a reader never sees half a file."""
    HUD_DIR.mkdir(parents=True, exist_ok=True)
    _seal(HUD_DIR, 0o755)
    tmp = HUD_DIR / ".now.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, HUD_DIR / "now.json")
    lines = payload.get("hud_lines") or []
    tmp = HUD_DIR / ".now.txt.tmp"
    tmp.write_text("\n".join(str(l) for l in lines) + "\n", encoding="utf-8")
    os.replace(tmp, HUD_DIR / "now.txt")
    log = HUD_DIR / "log.jsonl"
    entry = {k: v for k, v in payload.items() if k != "hud_lines"}
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if log.stat().st_size > HUD_LOG_MAX:
        keep = log.read_bytes()[-HUD_LOG_MAX // 2:]
        keep = keep[keep.find(b"\n") + 1:]   # start on a whole line
        tmp = HUD_DIR / ".log.tmp"
        tmp.write_bytes(keep)
        os.replace(tmp, log)
    readme = HUD_DIR / "README.md"
    if not readme.exists() or readme.read_text(encoding="utf-8") != HUD_README:
        readme.write_text(HUD_README, encoding="utf-8")
    for f in ("now.json", "now.txt", "log.jsonl", "README.md"):
        _seal(HUD_DIR / f, 0o644)
    return {"ok": True, "tick": payload.get("tick")}


def stats() -> dict:
    disk = shutil.disk_usage(HOME)
    mem = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            mem[k] = int(v.split()[0]) * 1024
    except (OSError, ValueError):
        pass
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        load = os.getloadavg()[0]
    except (OSError, ValueError, IndexError):
        uptime, load = 0.0, 0.0
    return {"disk_used": disk.used, "disk_total": disk.total, "mem_total": mem.get("MemTotal", 0),
            "mem_available": mem.get("MemAvailable", 0), "load": load, "uptime": uptime}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        auth = self.headers.get("Authorization", "")
        return bool(TOKEN) and hmac.compare_digest(auth.encode(), f"Bearer {TOKEN}".encode())

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/health":
            return self._send(200, {"ok": True})
        if url.path not in ("/log", "/tree", "/file", "/stats"):
            return self._send(404, {"error": "not found"})
        if not self._authorized():
            return self._send(401, {"error": "unauthorized"})
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/log":
                return self._send(200, log_tail(int(q.get("lines") or 300)))
            if url.path == "/tree":
                return self._send(200, tree())
            if url.path == "/file":
                return self._send(200, read_file(q.get("path", "")))
            return self._send(200, stats())
        except (OSError, ValueError) as exc:
            return self._send(500, {"error": str(exc)})

    def do_POST(self):
        if self.path not in ("/exec", "/hud"):
            return self._send(404, {"error": "not found"})
        if not self._authorized():
            return self._send(401, {"error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send(400, {"error": "bad request"})
        if length > 200_000:
            return self._send(413, {"error": "request too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("not an object")
        except ValueError:
            return self._send(400, {"error": "bad request"})
        if self.path == "/hud":
            try:
                return self._send(200, write_hud(body))
            except OSError as exc:
                return self._send(500, {"error": str(exc)})
        command = str(body.get("command") or "").strip()
        try:
            timeout = max(1, min(MAX_TIMEOUT, int(body.get("timeout") or 60)))
        except (ValueError, TypeError):
            return self._send(400, {"error": "bad request"})
        if not command:
            return self._send(400, {"error": "command is required"})
        self._send(200, run(command, timeout, str(body.get("cwd") or "")))

    def log_message(self, fmt, *args):
        pass


class DualStackServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6

    def server_bind(self):
        # One bind for IPv4 and IPv6.
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("MACHINE_TOKEN is not set")
    DualStackServer(("::", PORT), Handler).serve_forever()
