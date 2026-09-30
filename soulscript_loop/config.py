"""Loop configuration."""

import json
import logging
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger(__name__)


@dataclass
class LoopConfig:
    # ── Identity ──────────────────────────────────────────────────
    agent: str = "elysia"
    system_prompt: str = ""
    # Fixed stimulus sent every tick. Empty → built from senses each tick.
    stimulus: str = ""

    # ── Cadence ───────────────────────────────────────────────────
    ticks_per_loop: int = 15
    max_loops: int = 5                  # 0 = run forever
    tick_interval_seconds: float = 0.0  # pause between ticks (1.0 ≈ 1 Hz ceiling)
    loop_interval_seconds: float = 1800.0

    # ── Per-tick limits ───────────────────────────────────────────
    max_steps_per_tick: int = 3         # model ↔ tool round-trips
    max_tool_calls_per_tick: int = 15
    history_window: int = 20            # prior messages carried into each tick

    # ── Guards ────────────────────────────────────────────────────
    stale_streak_limit: int = 2         # identical ticks before auto-stop (0 = off)
    auto_pause_on_error_streak: int = 5 # consecutive errors before stop (0 = off)
    auto_pause_on_budget: bool = True
    per_tick_cap: float = 0.10          # USD; exceeding pauses the loop
    per_session_cap: float = 2.00       # USD; exceeding stops the loop

    # ── Storage / backend ─────────────────────────────────────────
    data_dir: str = "data"
    workbench: bool = True              # persistent scratch space at <data_dir>/workbench
    backend: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoopConfig":
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            log.warning("[config] Ignoring unknown keys: %s", ", ".join(unknown))
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_file(cls, path: str | Path) -> "LoopConfig":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
