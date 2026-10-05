"""Loop configuration (JSON). Unknown keys are ignored; numbers given as strings are coerced."""

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger(__name__)


@dataclass
class LoopConfig:
    # Identity
    agent: str = "elysia"
    system_prompt: str = ""

    # Wall-time cadence. Low energy slows it; surprise quickens it.
    base_interval_seconds: float = 120.0
    min_interval_seconds: float = 20.0
    max_interval_seconds: float = 1800.0
    max_rest_minutes: float = 240.0

    # Energy: a hard daily budget.
    daily_token_budget: int = 200_000
    daily_cost_cap: float = 2.00       # USD; 0 = tokens only
    max_tokens_per_tick: int = 30_000

    # Per-tick limits
    max_steps_per_tick: int = 4        # model ↔ tool round trips
    max_tool_calls_per_tick: int = 12
    history_window: int = 4            # earlier ticks carried as conversation

    # The field
    capacity_chars: int = 2400         # how much the field can hold at once
    capture_threshold: float = 0.45    # salience needed to pull focus involuntarily
    embedder: str = "auto"             # auto | minilm | hash

    # Metacognitive guards
    stale_streak_limit: int = 3        # identical ticks before a forced rest
    guard_rest_minutes: float = 30.0
    max_guard_rests: int = 3           # forced rests per session before stopping
    error_streak_limit: int = 5
    rumination_ticks: int = 5          # ticks on one focus without acting before the body notices

    # Storage, making, model
    data_dir: str = "data"
    workbench: bool = True
    sandbox: Dict[str, Any] = field(default_factory=lambda: {"enabled": False})
    machine: Dict[str, Any] = field(default_factory=lambda: {"enabled": False})
    backend: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoopConfig":
        out = cls()
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            log.warning("[config] ignoring unknown keys: %s", ", ".join(unknown))
        for f in fields(cls):
            if f.name not in data or data[f.name] is None:
                continue
            default = getattr(out, f.name)
            value = data[f.name]
            try:
                if isinstance(default, bool):
                    value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
                elif isinstance(default, int):
                    value = int(float(value))
                elif isinstance(default, float):
                    value = float(value)
                elif isinstance(default, dict):
                    if not isinstance(value, dict):
                        raise TypeError("expected an object")
                else:
                    value = str(value)
            except (TypeError, ValueError):
                log.warning("[config] bad value %s=%r — using default", f.name, value)
                continue
            setattr(out, f.name, value)
        out.min_interval_seconds = max(5.0, out.min_interval_seconds)
        out.max_interval_seconds = max(out.min_interval_seconds, out.max_interval_seconds)
        out.base_interval_seconds = min(max(out.base_interval_seconds, out.min_interval_seconds), out.max_interval_seconds)
        out.capacity_chars = max(600, out.capacity_chars)
        out.max_steps_per_tick = max(1, out.max_steps_per_tick)
        return out

    @classmethod
    def from_file(cls, path: str | Path) -> "LoopConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict:
        return asdict(self)
