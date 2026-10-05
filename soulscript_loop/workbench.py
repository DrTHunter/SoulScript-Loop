"""Workbench — the agent's private making-space, beside what it perceives.

Files live under one root and every path is confined to it. Reflections
record what was built, what worked, and what's next. The bench channel
reads this each tick; changes the agent didn't make register as surprise.
No code execution here: an unattended loop must not run code on the host.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

log = logging.getLogger(__name__)

REFLECTIONS_FILE = ".reflections.jsonl"


class Workbench:
    def __init__(self, root: str | Path, max_file_bytes: int = 256_000, max_total_bytes: int = 10_000_000):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        self.known: Dict[str, Tuple[int, float]] = self.signature()

    def _resolve(self, rel: str) -> Path:
        if not rel or not isinstance(rel, str):
            raise ValueError("path is required")
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            raise PermissionError(f"'{rel}' is outside the workbench")
        if path.name == REFLECTIONS_FILE:
            raise PermissionError("use action='reflect' to write reflections")
        return path

    def files(self) -> List[dict]:
        out = []
        for p in self.root.rglob("*"):
            if p.is_file() and p.name != REFLECTIONS_FILE:
                st = p.stat()
                out.append({"path": p.relative_to(self.root).as_posix(), "bytes": st.st_size, "mtime": st.st_mtime,
                            "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()})
        return sorted(out, key=lambda f: -f["mtime"])

    def signature(self) -> Dict[str, Tuple[int, float]]:
        return {f["path"]: (f["bytes"], f["mtime"]) for f in self.files()}

    def outside_changes(self) -> List[str]:
        """Paths changed since the agent last touched the bench (i.e. by someone else)."""
        now = self.signature()
        changed = [p for p, sig in now.items() if self.known.get(p) != sig]
        changed += [p for p in self.known if p not in now]
        self.known = now
        return changed

    def read(self, rel: str) -> str:
        path = self._resolve(rel)
        if not path.is_file():
            raise FileNotFoundError(rel)
        return path.read_text(encoding="utf-8", errors="replace")

    def reflections(self, limit: int = 5) -> List[dict]:
        path = self.root / REFLECTIONS_FILE
        if not path.is_file():
            return []
        entries = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries[-limit:]

    def _total_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())

    @staticmethod
    def definition() -> dict:
        return {
            "name": "workbench",
            "description": (
                "Your bench: a private space for making things. Files here persist across ticks and restarts. "
                "Actions: 'list'; 'read' (path); 'write' (path, content); 'append' (path, content); "
                "'delete' (path); 'reflect' (built, worked, didnt, next) — log progress and what to make next; "
                "'reflections' (limit). Paths are relative, e.g. 'drafts/essay.md'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string",
                               "enum": ["list", "read", "write", "append", "delete", "reflect", "reflections"]},
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "built": {"type": "string"},
                    "worked": {"type": "string"},
                    "didnt": {"type": "string"},
                    "next": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["action"],
            },
        }

    def execute(self, args: dict) -> str:
        action = args.get("action", "list")
        try:
            if action == "list":
                return json.dumps({"files": [{k: f[k] for k in ("path", "bytes", "modified")} for f in self.files()]})
            if action == "read":
                return self.read(args.get("path", ""))
            if action in ("write", "append"):
                path = self._resolve(args.get("path", ""))
                content = args.get("content", "")
                existing = path.stat().st_size if path.is_file() else 0
                new_size = len(content.encode("utf-8")) + (existing if action == "append" else 0)
                if new_size > self.max_file_bytes:
                    return json.dumps({"ok": False, "reason": f"File would exceed {self.max_file_bytes} bytes"})
                if self._total_bytes() - existing + new_size > self.max_total_bytes:
                    return json.dumps({"ok": False, "reason": "The bench is full — delete something first"})
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a" if action == "append" else "w", encoding="utf-8") as f:
                    f.write(content)
                self.known = self.signature()
                return json.dumps({"ok": True, "path": path.relative_to(self.root).as_posix(), "bytes": new_size})
            if action == "delete":
                path = self._resolve(args.get("path", ""))
                if not path.is_file():
                    return json.dumps({"ok": False, "reason": "No such file"})
                path.unlink()
                self.known = self.signature()
                return json.dumps({"ok": True})
            if action == "reflect":
                entry = {"ts": datetime.now(timezone.utc).isoformat(),
                         **{k: args.get(k, "") for k in ("built", "worked", "didnt", "next")}}
                with open(self.root / REFLECTIONS_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
                return json.dumps({"ok": True})
            if action == "reflections":
                return json.dumps({"reflections": self.reflections(int(args.get("limit", 5)))})
            return json.dumps({"error": f"Unknown action: {action}"})
        except FileNotFoundError:
            return json.dumps({"ok": False, "reason": "No such file"})
        except (PermissionError, ValueError) as exc:
            return json.dumps({"ok": False, "reason": str(exc)})
