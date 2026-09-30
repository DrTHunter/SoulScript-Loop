"""Runtime state of the loop: counters, tick history, journal, inbox."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

HISTORY_FILE = "loop_history.jsonl"
JOURNAL_FILE = "loop_journal.jsonl"


class LoopState:
    """Everything the runner, the control tool, and the senses share.

    Tick history and journal are appended to JSONL files under
    ``data_dir`` so the persona's record survives restarts.
    """

    def __init__(self, data_dir: Optional[str | Path] = None):
        self.data_dir = Path(data_dir) if data_dir else None
        self.tick_history: List[Dict[str, Any]] = []
        self.journal_entries: List[Dict[str, Any]] = []
        self.total_ticks: int = 0
        self.total_cost: float = 0.0
        self.reset_session()
        self.load_from_disk()

    def reset_session(self):
        """Reset per-run counters. History and journal are kept."""
        self.running: bool = False
        self.paused: bool = False
        self.task: Optional[asyncio.Task] = None
        self.current_tick: int = 0
        self.current_loop: int = 0
        self.session_cost: float = 0.0
        self.error_streak: int = 0
        self.stale_streak: int = 0
        self._recent_fingerprints: List[str] = []
        self.inbox: List[Dict[str, Any]] = []
        self.last_error: Optional[str] = None
        self.started_at: Optional[str] = None
        self.stopped_at: Optional[str] = None
        self.stop_reason: Optional[str] = None
        self.last_tick_at: Optional[float] = None  # monotonic seconds

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "paused": self.paused,
            "current_tick": self.current_tick,
            "total_ticks": self.total_ticks,
            "current_loop": self.current_loop,
            "total_cost": round(self.total_cost, 6),
            "session_cost": round(self.session_cost, 6),
            "error_streak": self.error_streak,
            "stale_streak": self.stale_streak,
            "inbox_pending": len(self.inbox),
            "last_error": self.last_error,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "stop_reason": self.stop_reason,
            "recent_ticks": self.tick_history[-20:],
            "recent_journal": self.journal_entries[-20:],
        }

    # ── Staleness ─────────────────────────────────────────────────

    def record_fingerprint(self, fingerprint: str) -> bool:
        """Record a tick fingerprint. Returns True if it matches the previous tick (stale)."""
        is_stale = bool(self._recent_fingerprints and self._recent_fingerprints[-1] == fingerprint)
        self._recent_fingerprints.append(fingerprint)
        if len(self._recent_fingerprints) > 10:
            self._recent_fingerprints = self._recent_fingerprints[-10:]
        if is_stale:
            self.stale_streak += 1
        else:
            self.stale_streak = 0
        return is_stale

    # ── History / journal ─────────────────────────────────────────

    def log_tick(self, tick_data: dict):
        self.tick_history.append(tick_data)
        if len(self.tick_history) > 200:
            self.tick_history = self.tick_history[-200:]
        self._append(HISTORY_FILE, tick_data)

    def log_journal(self, entry: dict):
        """Append a narrative journal entry."""
        self.journal_entries.append(entry)
        if len(self.journal_entries) > 500:
            self.journal_entries = self.journal_entries[-500:]
        self._append(JOURNAL_FILE, entry)

    def clear_journal(self):
        """Wipe journal from memory and disk."""
        self.journal_entries.clear()
        if self.data_dir:
            path = self.data_dir / JOURNAL_FILE
            try:
                if path.is_file():
                    path.unlink()
            except Exception as exc:
                log.warning("[loop] Failed to clear journal file: %s", exc)

    def load_from_disk(self):
        self.tick_history = self._read(HISTORY_FILE)[-200:]
        self.journal_entries = self._read(JOURNAL_FILE)[-500:]

    def _append(self, name: str, entry: dict):
        if not self.data_dir:
            return
        path = self.data_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as exc:
            log.warning("[loop] Failed to persist %s: %s", name, exc)

    def _read(self, name: str) -> List[Dict[str, Any]]:
        if not self.data_dir:
            return []
        path = self.data_dir / name
        if not path.is_file():
            return []
        entries: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except Exception as exc:
            log.warning("[loop] Failed to load %s: %s", name, exc)
            return []
        return entries
