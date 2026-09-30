"""Workbench — a persistent scratch space the persona builds in across ticks.

Files live under one root directory and every path is confined to it.
A reflection log records what she built, what worked, what didn't, and
what's next; the workbench sense shows her unfinished work every tick.

Code execution and self-made tools are deliberately NOT here — an
unattended loop must not run arbitrary code on the host. See the
README roadmap.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .tools import ToolRegistry

log = logging.getLogger(__name__)

REFLECTIONS_FILE = ".reflections.jsonl"


class Workbench:
    def __init__(self, root: str | Path, max_file_bytes: int = 256_000, max_total_bytes: int = 10_000_000):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes

    # ── Paths ─────────────────────────────────────────────────────

    def _resolve(self, rel: str) -> Path:
        if not rel or not isinstance(rel, str):
            raise ValueError("path is required")
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            raise PermissionError(f"'{rel}' is outside the workbench")
        if path.name == REFLECTIONS_FILE:
            raise PermissionError("use action='reflect' to write reflections")
        return path

    def files(self) -> list[dict]:
        out = []
        for p in sorted(self.root.rglob("*")):
            if p.is_file() and p.name != REFLECTIONS_FILE:
                stat = p.stat()
                out.append({
                    "path": p.relative_to(self.root).as_posix(),
                    "bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                })
        return out

    def _total_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())

    # ── Reflections ───────────────────────────────────────────────

    def reflections(self, limit: int = 5) -> list[dict]:
        path = self.root / REFLECTIONS_FILE
        if not path.is_file():
            return []
        entries = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries[-limit:]

    # ── Tool ──────────────────────────────────────────────────────

    @staticmethod
    def definition() -> dict:
        return {
            "name": "workbench",
            "description": (
                "Your persistent scratch space. Files here survive between ticks and restarts, "
                "so you can build something over many ticks and iterate on it. "
                "Actions: 'list' — list your files; 'read' — read a file; "
                "'write' — create or overwrite a file; 'append' — add to the end of a file; "
                "'delete' — remove a file; 'reflect' — log what you built, what worked, "
                "what didn't, and what to build next; 'reflections' — read recent reflections. "
                "Paths are relative to the workbench (e.g. 'drafts/poem.md')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "read", "write", "append", "delete", "reflect", "reflections"],
                    },
                    "path": {"type": "string", "description": "File path relative to the workbench."},
                    "content": {"type": "string", "description": "Text for write/append."},
                    "built": {"type": "string", "description": "reflect: what you built or changed."},
                    "worked": {"type": "string", "description": "reflect: what worked."},
                    "didnt": {"type": "string", "description": "reflect: what didn't work."},
                    "next": {"type": "string", "description": "reflect: what to build next."},
                    "limit": {"type": "integer", "description": "reflections: how many (default 5)."},
                },
                "required": ["action"],
            },
        }

    def execute(self, args: dict) -> str:
        action = args.get("action", "list")
        try:
            if action == "list":
                return json.dumps({"files": self.files()}, indent=2)

            if action == "read":
                path = self._resolve(args.get("path", ""))
                if not path.is_file():
                    return json.dumps({"ok": False, "reason": "No such file"})
                return path.read_text(encoding="utf-8", errors="replace")

            if action in ("write", "append"):
                path = self._resolve(args.get("path", ""))
                content = args.get("content", "")
                existing = path.stat().st_size if path.is_file() else 0
                new_size = len(content.encode("utf-8")) + (existing if action == "append" else 0)
                if new_size > self.max_file_bytes:
                    return json.dumps({"ok": False, "reason": f"File would exceed {self.max_file_bytes} bytes"})
                if self._total_bytes() - existing + new_size > self.max_total_bytes:
                    return json.dumps({"ok": False, "reason": "Workbench is full — delete something first"})
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a" if action == "append" else "w", encoding="utf-8") as f:
                    f.write(content)
                return json.dumps({"ok": True, "path": path.relative_to(self.root).as_posix(), "bytes": new_size})

            if action == "delete":
                path = self._resolve(args.get("path", ""))
                if not path.is_file():
                    return json.dumps({"ok": False, "reason": "No such file"})
                path.unlink()
                return json.dumps({"ok": True})

            if action == "reflect":
                entry = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    **{k: args.get(k, "") for k in ("built", "worked", "didnt", "next")},
                }
                with open(self.root / REFLECTIONS_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
                return json.dumps({"ok": True})

            if action == "reflections":
                return json.dumps({"reflections": self.reflections(args.get("limit", 5))}, indent=2)

            return json.dumps({"error": f"Unknown action: {action}"})
        except (PermissionError, ValueError) as exc:
            return json.dumps({"ok": False, "reason": str(exc)})

    # ── Sense ─────────────────────────────────────────────────────

    def sense(self, ctx) -> Optional[str]:
        """Show her what's on the bench, so unfinished work pulls her back."""
        files = self.files()
        last = self.reflections(1)
        if not files and not last:
            return None
        lines = [f"workbench: {len(files)} file(s)"]
        for f in files[-8:]:
            lines.append(f"  - {f['path']} ({f['bytes']} bytes)")
        if len(files) > 8:
            lines.append(f"  … and {len(files) - 8} more")
        if last and last[0].get("next"):
            lines.append(f"  you planned next: {last[0]['next']}")
        return "\n".join(lines)

    def register(self, registry: ToolRegistry):
        registry.register(self.definition(), self.execute)
