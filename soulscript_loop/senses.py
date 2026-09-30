"""Senses — channels the persona receives each tick but cannot author.

A sense is any callable ``(SenseContext) -> str | None``. The runner
calls every sense at the start of a tick and writes the non-empty
readings into the stimulus under a SENSES header. The model never
produces these values; the runner measures them. Add your own
(system metrics, prediction-error history, a sensor feed) by passing
a list of senses to ``LoopRunner``.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional

from .config import LoopConfig
from .state import LoopState

log = logging.getLogger(__name__)


@dataclass
class SenseContext:
    state: LoopState
    config: LoopConfig
    now: datetime          # wall clock, UTC
    monotonic: float       # time.monotonic() at tick start
    tick: int
    loop: int


Sense = Callable[[SenseContext], Optional[str]]


def _fmt_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def clock_sense(ctx: SenseContext) -> Optional[str]:
    """Wall-clock time, how long the loop has been awake, time since last tick."""
    parts = [f"{ctx.now:%a %Y-%m-%d %H:%M} UTC ({_part_of_day(ctx.now.hour)})"]
    if ctx.state.started_at:
        started = datetime.fromisoformat(ctx.state.started_at)
        parts.append(f"awake {_fmt_duration((ctx.now - started).total_seconds())}")
    if ctx.state.last_tick_at is not None:
        parts.append(f"{ctx.monotonic - ctx.state.last_tick_at:.1f}s since last tick")
    return "clock: " + " · ".join(parts)


def budget_sense(ctx: SenseContext) -> Optional[str]:
    """Remaining attention budget — the loop's finitude."""
    cap = ctx.config.per_session_cap
    spent = ctx.state.session_cost
    if not cap:
        return f"budget: ${spent:.4f} spent this session (no cap)"
    left = max(0.0, 1 - spent / cap) * 100
    return f"budget: ${spent:.4f} of ${cap:.2f} session budget spent ({left:.0f}% left)"


def inbox_sense(ctx: SenseContext) -> Optional[str]:
    """Messages that arrived while the loop was already running."""
    if not ctx.state.inbox:
        return None
    lines = [f"inbox: {len(ctx.state.inbox)} unanswered message(s)"]
    for msg in ctx.state.inbox:
        received = datetime.fromisoformat(msg["received_at"])
        age = _fmt_duration((ctx.now - received).total_seconds())
        lines.append(f"  - from {msg['sender']} ({age} ago): {msg['text']}")
    return "\n".join(lines)


def last_tick_sense(ctx: SenseContext) -> Optional[str]:
    """What happened last tick, so the stream carries forward instead of restarting."""
    if not ctx.state.journal_entries:
        return None
    narrative = ctx.state.journal_entries[-1].get("narrative", "")
    if not narrative:
        return None
    return (
        f"last tick: {narrative}\n"
        "  Do NOT repeat the same action. Build on what was done or move to the next task."
    )


def repetition_sense(ctx: SenseContext) -> Optional[str]:
    """Warn when consecutive ticks were identical — the loop can feel itself stalling."""
    if ctx.state.stale_streak <= 0:
        return None
    remaining = ctx.config.stale_streak_limit - ctx.state.stale_streak
    return (
        f"⚠ repetition: your last {ctx.state.stale_streak} tick(s) were identical. "
        f"You will be auto-stopped in {remaining} more stale tick(s). "
        "You MUST do something DIFFERENT this tick or call loop_control(action='request_stop')."
    )


DEFAULT_SENSES: List[Sense] = [
    clock_sense,
    budget_sense,
    inbox_sense,
    last_tick_sense,
    repetition_sense,
]

DEFAULT_INSTRUCTIONS = (
    "INSTRUCTIONS:\n"
    "1. Read your senses. Anything in the inbox arrived while you were mid-thought — "
    "decide whether it changes what you were doing.\n"
    "2. Take the most meaningful action available to you. Use your tools.\n"
    "3. Report what you did and what you intend to do next tick.\n\n"
    "IMPORTANT: If you have nothing meaningful left to do, are stuck repeating "
    "the same actions, or continued execution is unproductive, call "
    "loop_control(action='request_stop') with a reason. "
    "Do NOT keep looping if there is nothing meaningful left to do."
)


def _read(sense: Sense, ctx: SenseContext) -> Optional[str]:
    try:
        return sense(ctx)
    except Exception as exc:
        name = getattr(sense, "__name__", "sense")
        log.warning("[senses] %s failed: %s", name, exc)
        return f"{name}: (no signal — {exc})"


def build_stimulus(ctx: SenseContext, senses: List[Sense], instructions: str = DEFAULT_INSTRUCTIONS) -> str:
    readings = [r for r in (_read(sense, ctx) for sense in senses) if r]
    header = f"[Loop] Tick {ctx.tick}/{ctx.config.ticks_per_loop} — loop {ctx.loop}."
    body = "SENSES\n" + "\n".join(f"- {r}" for r in readings) if readings else ""
    return "\n\n".join(p for p in (header, body, instructions) if p)
