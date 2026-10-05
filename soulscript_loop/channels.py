"""Sensory channels — signals the agent receives but cannot author.

Each channel reads raw state and returns a Signal: numeric features for
the predictor (which turns them into surprise) and items for the field
(or its HUD gauges). The model never writes these; the daemon measures them.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from .budget import DailyBudget
from .prediction import fmt_quantity
from .workbench import Workbench
from .world import InnerWorld, _clip, fmt_age

log = logging.getLogger(__name__)


@dataclass
class Signal:
    channel: str
    features: Dict[str, float] = field(default_factory=dict)
    items: List[dict] = field(default_factory=list)     # kwargs for InnerWorld.upsert
    resolve: List[str] = field(default_factory=list)    # item keys that were dealt with
    clear: List[str] = field(default_factory=list)      # item keys that simply stopped
    events: List[str] = field(default_factory=list)     # what "happened", for expectations
    reading: str = ""                                   # one-line summary for the monitor


@dataclass
class ChannelContext:
    now: float
    tick: int
    world: InnerWorld
    budget: DailyBudget
    last_tick_at: Optional[float] = None
    last: dict = field(default_factory=dict)            # previous tick: tokens, latency, tools, error
    new_messages: List[dict] = field(default_factory=list)
    pending_tasks: List[dict] = field(default_factory=list)
    workbench: Optional[Workbench] = None
    stale_streak: int = 0
    stale_limit: int = 3
    rumination_ticks: int = 5


Channel = Callable[[ChannelContext], Optional[Signal]]


def part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def time_channel(ctx: ChannelContext) -> Signal:
    dt = datetime.fromtimestamp(ctx.now, timezone.utc)
    pod = part_of_day(dt.hour)
    gap = ctx.now - ctx.last_tick_at if ctx.last_tick_at else None
    text = f"{pod} light · {dt:%H:%M} UTC · " + (f"{fmt_age(gap)} since you last looked" if gap else "you just woke")
    sig = Signal("time", reading=text)
    sig.items.append(dict(key="time", kind="time", source="time", text=text, gist=f"{pod}, {dt:%H:%M}",
                          salience=0.2, valence=0.0, mode="level", anchor=True, meta={"trace": f"{pod} light"}))
    if gap is not None:
        sig.features["time.gap"] = gap
    return sig


def body_channel(ctx: ChannelContext) -> Signal:
    b = ctx.budget
    energy = b.energy
    pct = round(energy * 100)
    text = f"energy {pct}% — {b.tokens_left:,} of {b.tokens_per_day:,} tokens left today"
    last_tokens = ctx.last.get("tokens")
    if last_tokens:
        text += f"; your last thought used {fmt_quantity(last_tokens, 'tok')}"
    valence = -(0.35 - energy) * 2 if energy < 0.35 else 0.1 * (energy - 0.5)
    sig = Signal("body", reading=text)
    sig.items.append(dict(key="energy", kind="energy", source="body", text=text, gist=f"energy {pct}%",
                          salience=0.15 + 0.6 * (1 - energy) ** 2, valence=valence, mode="level",
                          anchor=True, meta={"trace": f"energy {pct}%"}))

    if ctx.last:
        tools = ctx.last.get("tools", [])
        fails = [t["tool"] for t in tools if not t.get("ok", True)]
        if ctx.last.get("error"):
            body = f"your last thought broke off: {_clip(str(ctx.last['error']), 120)}"
            v, s = -0.45, 0.7
        elif tools:
            names = list(dict.fromkeys(t["tool"] for t in tools))
            body = f"you just used {', '.join(names)}"
            if fails:
                body += f"; {len(fails)} call(s) failed ({', '.join(dict.fromkeys(fails))})"
            v, s = (-0.25, 0.6) if fails else (0.15, 0.3)
        else:
            body = "you only thought last time; your hands didn't move"
            v, s = 0.0, 0.25
        sig.items.append(dict(key="proprio", kind="body", source="body", text=body, gist=_clip(body, 48),
                              salience=s, valence=v, mode="level", anchor=True, meta={"trace": "the feel of your last action"}))
        if ctx.last.get("tokens"):
            sig.features["body.burn"] = ctx.last["tokens"]
        if ctx.last.get("latency"):
            sig.features["body.latency"] = ctx.last["latency"]
        if tools:
            sig.features["body.tool_fail"] = 1.0 if fails else 0.0

    if ctx.stale_streak > 0:
        left = max(0, ctx.stale_limit - ctx.stale_streak)
        sig.items.append(dict(key="repetition", kind="alert", source="body",
                              text=f"you feel yourself repeating — your last {ctx.stale_streak + 1} actions were the same. "
                                   f"{left} more and you'll be made to rest.",
                              gist="you are repeating yourself", salience=0.85, valence=-0.5))
    else:
        sig.clear.append("repetition")

    w = ctx.world
    if w.dwell >= ctx.rumination_ticks and not ctx.last.get("tools"):
        sig.items.append(dict(key="rumination", kind="alert", source="body",
                              text=f"you've held your focus on {w.focus_label()} for {w.dwell} ticks without doing anything",
                              gist="you are circling", salience=0.6, valence=-0.3))
    else:
        sig.clear.append("rumination")
    return sig


def door_channel(ctx: ChannelContext) -> Signal:
    w = ctx.world
    sig = Signal("door")
    arrived = 0
    for m in ctx.new_messages:
        arrived += 1
        sender = m.get("sender", "someone")
        sig.items.append(dict(
            key=f"msg:{m['id']}", kind="message", source="door",
            text=f"{sender}: {_clip(m.get('text', ''), 600)}", gist=f"{sender}: {_clip(m.get('text', ''), 48)}",
            salience=0.85, valence=-0.3, grows=0.25, meta={"message_id": m["id"], "sender": sender},
        ))
    pending_ids = set()
    for t in ctx.pending_tasks:
        pending_ids.add(t["id"])
        key = f"task:{t['id']}"
        if key not in w.keys:
            arrived += 1
        prio = t.get("priority", "normal")
        task = t.get("task") or t.get("subject") or ""
        sig.items.append(dict(
            key=key, kind="task", source="door",
            text=f"task from {t.get('from', 'operator')} ({prio}, inbox id {t['id']}): {_clip(task, 400)}",
            gist=f"task: {_clip(task, 48)}", salience=0.85 if prio in ("high", "urgent") else 0.6,
            valence=-0.15, grows=0.08, meta={"inbox_id": t["id"]},
        ))
    for key in list(w.keys):
        if key.startswith("task:") and key[5:] not in pending_ids:
            sig.resolve.append(key)
    sig.features["door.arrival"] = 1.0 if arrived else 0.0
    if arrived:
        sig.events.append("door")
    waiting = sum(1 for i in w.items.values() if i.kind in ("message", "task") and not i.resolved)
    sig.reading = f"{arrived} arrived · {len(ctx.pending_tasks)} inbox task(s) pending · {waiting} waiting"
    return sig


def bench_channel(ctx: ChannelContext) -> Optional[Signal]:
    wb = ctx.workbench
    if not wb:
        return None
    sig = Signal("bench")
    outside = wb.outside_changes()
    files = wb.files()
    shown = files[:4]
    for f in shown:
        size = f"{f['bytes'] / 1024:.1f} KB" if f["bytes"] >= 1024 else f"{f['bytes']} B"
        try:
            preview = _clip(wb.read(f["path"])[:400], 160)
        except Exception:
            preview = ""
        sig.items.append(dict(key=f"file:{f['path']}", kind="work", source="bench",
                              text=f"{f['path']} ({size})" + (f": {preview}" if preview else ""),
                              gist=f["path"], salience=0.35, valence=0.15,
                              meta={"path": f["path"], "mtime": f["mtime"]}))
    shown_keys = {f"file:{f['path']}" for f in shown}
    sig.clear += [k for k in ctx.world.keys if k.startswith("file:") and k not in shown_keys]

    last = wb.reflections(1)
    if last and last[0].get("next"):
        sig.items.append(dict(key="plan", kind="plan", source="bench",
                              text=f"you planned next: {_clip(last[0]['next'], 300)}",
                              gist=f"next: {_clip(last[0]['next'], 48)}", salience=0.5, valence=0.1))
    if outside:
        sig.items.append(dict(key=f"outside:{ctx.tick}", kind="note", source="bench",
                              text=f"changed while you weren't looking: {', '.join(outside[:5])}",
                              gist="someone touched the bench", salience=0.6, valence=0.0))
        sig.events.append("bench")
    sig.features["bench.outside_change"] = 1.0 if outside else 0.0
    sig.reading = f"{len(files)} file(s)" + (f" · {len(outside)} changed from outside" if outside else "")
    return sig


DEFAULT_CHANNELS: List[Channel] = [time_channel, body_channel, door_channel, bench_channel]
