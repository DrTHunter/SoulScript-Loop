"""The wall-time daemon: the agent keeps running between messages.

Each tick: sense → update → predict → attend → feel → render → think/act
→ guard → record → sleep. Sleep is on wall time and is interruptible:
a message at the door wakes it early. Energy (the daily budget) slows
the cadence as it drains; surprise quickens it. When energy runs out the
daemon sleeps until the budget resets.

The daemon is host-agnostic. A Host builds the persona prompt, calls the
model, and runs the extra tools; ``host.StandaloneHost`` does that with an
OpenAI-compatible backend and a ToolRegistry, and the OrionForge web app
supplies its own.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Protocol, Tuple

from .backend import Completion
from .budget import DailyBudget
from .channels import DEFAULT_CHANNELS, ChannelContext, Signal, part_of_day
from .config import LoopConfig
from .tools import LoopTools
from .workbench import Workbench
from .embedding import Embedder, HashEmbedder
from .world import InnerWorld, Item, _clip, fmt_age

log = logging.getLogger(__name__)

STAGES = ["sense", "update", "predict", "attend", "feel", "render", "think", "act", "guard", "record", "sleep"]
STAGE_ABOUT = {
    "sense": "channels read time, energy, body, door, bench",
    "update": "time passes: decay, growth of unanswered tension; new things placed",
    "predict": "observations compared to beliefs → surprise; expectations checked",
    "attend": "relatedness measured; strong arrivals pull focus; field laid out around it; capacity enforced",
    "feel": "mood read off the field",
    "render": "the field written as a HUD",
    "think": "the model sees through the field",
    "act": "tool calls",
    "guard": "repetition, rumination, error streaks",
    "record": "budget spent, logs and world saved",
    "sleep": "wall-time wait, woken early by messages",
}

# Host tools the loop never offers (a host can add names here).
EXCLUDED_TOOLS: set = set()

LOOP_PREAMBLE = """\
You are running continuously. You are not waiting for a message — you are already here, seeing.

Each tick you wake into your FIELD: the world as it appears to you right now, digital or real, organized around whatever you are focused on. Your focus can be anything — a message, a file, a memory, a search result, a person, a question you are turning over. The things most related to it sit CLOSE and clear; looser connections are AROUND you as a gist; everything else is a faint trace at the EDGE. Shift your focus and the field rearranges. Along the top runs your HUD: time, energy, how many are waiting for you, how full your field is, and the feel of your last action. "!" ALERTS are surprises — things that broke your expectations. Strong new arrivals pull your focus on their own. Things fade when you stop looking at them, and you can only hold so much at once. Your mood is not chosen — it is read from the field.

How to act:
- attend — focus on an [item], a topic, or a source; unfocus to let your gaze wander; hold what matters; resolve what's dealt with; set intentions; make predictions (expect) you'll feel met or broken.
- looking is acting: when you use a tool (memory, search, inbox, your bench…), what you see enters your field and becomes your focus.
- reply — answer someone waiting at the door.
- workbench — make things.
- loop_control — rest when nothing is worth the energy (a message still wakes you), or stop.

Energy is finite; every thought spends today's budget. Don't describe your field back. See through it: briefly say what you're doing and why, then do it."""


class Host(Protocol):
    def prepare(self, agent: str, view: str) -> Tuple[List[dict], List[dict]]: ...
    async def complete(self, config: LoopConfig, messages: List[dict], tools: List[dict]) -> Completion: ...
    def call_tool(self, agent: str, name: str, args: dict) -> str: ...
    def after_response(self, agent: str, text: str) -> str: ...
    def pending_tasks(self) -> List[dict]: ...


def _iso(ts: Optional[float] = None) -> str:
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).isoformat()


def fingerprint(result: dict) -> str:
    parts = [f"{t['tool']}({','.join(f'{k}={str(v)[:80]}' for k, v in sorted((t.get('arguments') or {}).items()))})"
             for t in result.get("tool_calls", [])]
    parts.append(" ".join((result.get("response") or "").lower().split())[:500])
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def narrate(result: dict) -> str:
    if result.get("error"):
        return f"Broke off: {_clip(str(result['error']), 300)}"
    parts = []
    names = list(dict.fromkeys(t["tool"] for t in result.get("tool_calls", [])))
    if names:
        parts.append(f"Used {', '.join(names)}.")
    resp = " ".join((result.get("response") or "").split())
    parts.append(_clip(resp, 600) if resp else "Said nothing.")
    return " ".join(parts)


class JsonlLog:
    def __init__(self, path: Path, keep: int):
        self.path = path
        self.items: Deque[dict] = deque(maxlen=keep)
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        with contextlib.suppress(json.JSONDecodeError):
                            self.items.append(json.loads(line))

    def append(self, entry: dict):
        self.items.append(entry)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("[loop] could not write %s: %s", self.path.name, exc)

    def tail(self, n: int) -> List[dict]:
        return list(self.items)[-n:] if n > 0 else []

    def clear(self):
        self.items.clear()
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


class LoopDaemon:
    def __init__(self, host: Host, config: LoopConfig, data_dir: Path, embedder: Optional[Embedder] = None):
        self.host = host
        self.embedder = embedder or HashEmbedder()
        self.config = config
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.world = self._load_world()
        self.budget = DailyBudget(self.data_dir / "budget.json", config.daily_token_budget, config.daily_cost_cap)
        self.workbench = Workbench(self.data_dir / "workbench") if config.workbench else None
        self.channels = list(DEFAULT_CHANNELS)
        self.tools = LoopTools(self)

        self.ticks = JsonlLog(self.data_dir / "ticks.jsonl", 200)
        self.journal = JsonlLog(self.data_dir / "journal.jsonl", 500)
        self.events = JsonlLog(self.data_dir / "events.jsonl", 400)
        self.conversation = JsonlLog(self.data_dir / "conversation.jsonl", 300)

        self.task: Optional[asyncio.Task] = None
        self.running = False
        self.paused = False
        self.phase = "idle"
        self.stage: Optional[str] = None
        self.started_at: Optional[float] = None
        self.stopped_at: Optional[float] = None
        self.stop_reason: Optional[str] = None
        self.session_ticks = 0
        self.session_tokens = 0
        self.session_cost = 0.0
        self.error_streak = 0
        self.stale_streak = 0
        self.guard_rests = 0
        self.last_error: Optional[str] = None
        self.next_wake_at: Optional[float] = None
        self.wake_reason = "start"
        self.rest_request: Optional[Tuple[float, str]] = None
        self.resting: Optional[str] = None
        self._wake = asyncio.Event()
        self._wake_cause: Optional[str] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._fingerprints: Deque[str] = deque(maxlen=10)

        self.processes: Dict[str, dict] = {s: {"stage": s, "about": STAGE_ABOUT[s], "status": "idle", "runs": 0,
                                               "last_ms": None, "avg_ms": None, "last_at": None, "note": "",
                                               "errors": 0} for s in STAGES}
        self.channel_status: Dict[str, dict] = {}

        saved = self._read_json("state.json")
        self.last_tick_at: Optional[float] = saved.get("last_tick_at")
        self.last_result: dict = saved.get("last_result", {})
        self.queue: List[dict] = saved.get("queue", [])
        self.history: List[dict] = [{"view": t.get("view_head", ""), "response": t.get("response", "")}
                                    for t in self.ticks.tail(config.history_window)]

    # ── Persistence ───────────────────────────────────────────────

    def _read_json(self, name: str) -> dict:
        try:
            return json.loads((self.data_dir / name).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except Exception as exc:
            log.warning("[loop] %s unreadable: %s", name, exc)
            return {}

    def _write_json(self, name: str, data: dict):
        tmp = self.data_dir / f".{name}.tmp"
        tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
        tmp.replace(self.data_dir / name)

    def _load_world(self) -> InnerWorld:
        data = self._read_json("world.json")
        c = self.config
        return InnerWorld.from_dict(data, c.capacity_chars, c.capture_threshold, self.embedder) if data \
            else InnerWorld(c.capacity_chars, c.capture_threshold, self.embedder)

    def save(self):
        try:
            self._write_json("world.json", self.world.to_dict())
            self._write_json("state.json", {"last_tick_at": self.last_tick_at, "last_result": self.last_result,
                                            "queue": self.queue})
        except OSError as exc:
            log.warning("[loop] save failed: %s", exc)

    def apply_config(self, config: LoopConfig):
        self.config = config
        self.world.capacity = config.capacity_chars
        self.world.capture_threshold = config.capture_threshold
        self.budget.tokens_per_day = max(1, config.daily_token_budget)
        self.budget.cost_per_day = config.daily_cost_cap

    def reset_world(self):
        if self.running:
            raise RuntimeError("Stop the loop before resetting its world")
        self.world = InnerWorld(self.config.capacity_chars, self.config.capture_threshold, self.embedder)
        self.last_tick_at, self.last_result, self.history = None, {}, []
        self.save()
        self.event("reset", "the field was cleared")

    # ── Outside interface ─────────────────────────────────────────

    def event(self, kind: str, text: str):
        self.events.append({"ts": _iso(), "tick": self.world.tick, "kind": kind, "text": text})

    def _poke(self, cause: str):
        """Wake the sleeper. Safe from worker threads (chat tools run off the event loop)."""
        self._wake_cause = cause
        loop = self._loop
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if loop is not None and current is not loop and loop.is_running():
            loop.call_soon_threadsafe(self._wake.set)
        else:
            self._wake.set()

    def start(self) -> asyncio.Task:
        if self.running:
            raise RuntimeError("Loop already running")
        self.task = asyncio.create_task(self.run())
        return self.task

    def stop(self, reason: str = "operator"):
        self.request_stop(reason)
        if self.task and not self.task.done() and self.stage not in ("think", "act"):
            self.task.cancel()

    def request_stop(self, reason: str):
        self.stop_reason = reason
        self.running = False
        self._poke("stop")

    def pause(self):
        self.paused = True
        self._poke("pause")

    def resume(self):
        self.paused = False
        self._poke("resume")

    def request_rest(self, minutes: float, reason: str) -> float:
        minutes = max(1.0, min(self.config.max_rest_minutes, minutes))
        self.rest_request = (minutes * 60, reason)
        return minutes

    def post_message(self, text: str, sender: str = "operator") -> dict:
        msg = {"id": uuid.uuid4().hex[:10], "ts": _iso(), "sender": sender, "text": text.strip()[:4000]}
        self.queue.append(msg)
        self.conversation.append({"id": msg["id"], "ts": msg["ts"], "role": "operator", "sender": sender, "text": msg["text"]})
        self.event("message", f"{sender} at the door: {_clip(msg['text'], 80)}")
        self.save()
        self._poke("message")
        return msg

    def record_reply(self, text: str, item: Optional[Item]):
        in_reply_to = item.meta.get("message_id") if item else None
        self.conversation.append({"id": uuid.uuid4().hex[:10], "ts": _iso(), "role": "agent",
                                  "sender": self.config.agent, "text": text, "in_reply_to": in_reply_to})
        if item:
            self.world.resolve(item)
        self.event("reply", _clip(text, 100))

    # ── Monitoring ────────────────────────────────────────────────

    @contextlib.contextmanager
    def _stage(self, name: str, note: str = ""):
        prev = self.stage
        self.stage = name
        p = self.processes[name]
        p["status"] = "running"
        p["last_at"] = _iso()
        t0 = time.perf_counter()
        try:
            yield p
            p["status"] = "ok"
        except Exception:
            p["status"] = "error"
            p["errors"] += 1
            raise
        finally:
            ms = (time.perf_counter() - t0) * 1000
            p["runs"] += 1
            p["last_ms"] = round(ms, 1)
            p["avg_ms"] = round(ms if p["avg_ms"] is None else 0.8 * p["avg_ms"] + 0.2 * ms, 1)
            if note and not p["note"]:
                p["note"] = note
            self.stage = prev

    def status(self) -> dict:
        w = self.world
        waiting = [i for i in w.items.values() if i.kind in ("message", "task") and not i.resolved]
        return {
            "running": self.running, "paused": self.paused, "phase": self.phase, "stage": self.stage,
            "started_at": _iso(self.started_at) if self.started_at else None,
            "stopped_at": _iso(self.stopped_at) if self.stopped_at else None,
            "stop_reason": self.stop_reason,
            "tick": w.tick, "session_ticks": self.session_ticks,
            "session_tokens": self.session_tokens, "session_cost": round(self.session_cost, 6),
            "error_streak": self.error_streak, "stale_streak": self.stale_streak,
            "guard_rests": self.guard_rests, "last_error": self.last_error,
            "next_wake_at": _iso(self.next_wake_at) if self.next_wake_at else None,
            "next_wake_in": round(self.next_wake_at - time.time()) if self.next_wake_at else None,
            "wake_reason": self.wake_reason, "resting": self.resting,
            "last_tick_at": _iso(self.last_tick_at) if self.last_tick_at else None,
            "focus": w.focus_item or "", "focus_name": w.focus_label(), "dwell": w.dwell,
            "mood": w.mood, "budget": self.budget.to_dict(),
            "capacity": {"used": w.used(time.time()), "of": w.capacity},
            "queue": len(self.queue), "waiting": len(waiting),
            "agent": self.config.agent, "model": self.config.backend.get("model", "") or "(backend default)",
            "processes": [self.processes[s] for s in STAGES],
            "channels": self.channel_status,
        }

    # ── The loop ──────────────────────────────────────────────────

    async def run(self):
        self._loop = asyncio.get_running_loop()
        self.running, self.paused = True, False
        self.started_at, self.stopped_at, self.stop_reason = time.time(), None, None
        self.session_ticks = self.session_tokens = self.guard_rests = 0
        self.session_cost = 0.0
        self.error_streak = self.stale_streak = 0
        self.wake_reason = "start"
        self.event("start", f"{self.config.agent} woke")
        try:
            while self.running:
                if self.paused:
                    self.phase = "paused"
                    while self.paused and self.running:
                        await self._wait(3600)
                    continue
                if self.budget.exhausted:
                    self.phase = "exhausted"
                    self.event("budget", "energy spent — sleeping until the daily budget resets")
                    await self._sleep(self.budget.seconds_until_reset(), wake_on_message=False)
                    continue
                self.phase = "ticking"
                try:
                    await self.tick()
                except Exception as exc:
                    log.exception("[loop] tick failed")
                    self.error_streak += 1
                    self.last_error = f"tick failed: {exc}"
                    self.event("error", _clip(self.last_error, 200))
                    if self.config.error_streak_limit and self.error_streak >= self.config.error_streak_limit:
                        self.request_stop(f"guard: {self.error_streak} errors in a row")
                if self.running and not self.paused:
                    await self._sleep(*self._next_interval())
        except asyncio.CancelledError:
            self.stop_reason = self.stop_reason or "cancelled"
        except Exception as exc:
            log.exception("[loop] daemon crashed")
            self.stop_reason = f"crashed: {exc}"
        finally:
            self.running = False
            self.phase = "stopped"
            self.stage = None
            self.next_wake_at = None
            self.stopped_at = time.time()
            self.event("stop", self.stop_reason or "stopped")
            self.save()

    async def _wait(self, timeout: float) -> Optional[str]:
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=max(0.0, timeout))
        except asyncio.TimeoutError:
            return None
        self._wake.clear()
        cause, self._wake_cause = self._wake_cause, None
        return cause

    def _next_interval(self) -> Tuple[float, Optional[str]]:
        if self.rest_request:
            secs, reason = self.rest_request
            self.rest_request = None
            return secs, reason
        c = self.config
        secs = c.base_interval_seconds
        energy = self.budget.energy
        if energy < 0.5:
            secs *= 1 + (0.5 - energy) * 4
        secs /= 1 + self.world.arousal * 1.5
        return max(c.min_interval_seconds, min(c.max_interval_seconds, secs)), None

    async def _sleep(self, seconds: float, rest_reason: Optional[str] = None, wake_on_message: bool = True):
        self.resting = rest_reason
        if rest_reason:
            self.event("rest", f"resting {seconds / 60:.0f}m — {rest_reason}")
        if self.phase != "exhausted":
            self.phase = "resting" if rest_reason else "sleeping"
        self.next_wake_at = time.time() + seconds
        with self._stage("sleep") as p:
            reason = "timer"
            while self.running and not self.paused:
                remaining = self.next_wake_at - time.time()
                if remaining <= 0:
                    break
                cause = await self._wait(remaining)
                if cause == "message" and wake_on_message:
                    reason = "message"
                    break
                if cause in ("stop", "pause", "poke"):
                    reason = cause
                    break
            p["note"] = f"woke: {reason}"
        self.wake_reason = ("rest_" + reason) if rest_reason else reason
        if reason == "message":
            self.event("wake", "a message at the door woke you" + (" from rest" if rest_reason else ""))
        self.next_wake_at = None
        self.resting = None

    def wake_now(self):
        self._poke("poke")

    def _woke_line(self, gap: Optional[float]) -> str:
        r = self.wake_reason
        if r == "start":
            return "You've just woken up." if not self.last_tick_at else f"You wake again after {fmt_age(gap or 0)} away."
        if r.endswith("message"):
            return "Someone at the door woke you" + (" from your rest." if r.startswith("rest_") else ".")
        if r.startswith("rest_"):
            return f"You wake from rest after {fmt_age(gap or 0)}."
        if r == "poke":
            return "You were nudged awake."
        return f"You woke on your own after {fmt_age(gap or 0)}." if gap else "You woke on your own."

    async def tick(self):
        c, w = self.config, self.world
        now = time.time()
        w.begin(w.tick + 1)
        gap = now - self.last_tick_at if self.last_tick_at else None

        with self._stage("sense") as p:
            new_msgs, self.queue = list(self.queue), []
            try:
                tasks = await asyncio.to_thread(self.host.pending_tasks)
            except Exception as exc:
                log.warning("[loop] inbox read failed: %s", exc)
                tasks = []
            ctx = ChannelContext(
                now=now, tick=w.tick, world=w, budget=self.budget, last_tick_at=self.last_tick_at,
                last=self.last_result, new_messages=new_msgs, pending_tasks=tasks, workbench=self.workbench,
                stale_streak=self.stale_streak, stale_limit=c.stale_streak_limit, rumination_ticks=c.rumination_ticks,
            )
            signals: List[Signal] = []
            for ch in self.channels:
                name = ch.__name__.replace("_channel", "")
                try:
                    sig = ch(ctx)
                except Exception as exc:
                    log.warning("[loop] channel %s failed: %s", name, exc)
                    self.channel_status[name] = {"channel": name, "at": _iso(now), "ok": False, "reading": str(exc)}
                    continue
                if sig:
                    signals.append(sig)
                    self.channel_status[sig.channel] = {"channel": sig.channel, "at": _iso(now), "ok": True,
                                                        "reading": sig.reading, "features": sig.features,
                                                        "items": len(sig.items)}
            p["note"] = f"{len(signals)} channels · {len(new_msgs)} message(s)"

        with self._stage("update") as p:
            w.decay(now)
            for sig in signals:
                for spec in sig.items:
                    w.upsert(now=now, **spec)
                for key in sig.resolve:
                    it = w.get(key)
                    if it:
                        w.resolve(it, now)
                for key in sig.clear:
                    it = w.get(key)
                    if it:
                        w.drop(it, reason="cleared")
            p["note"] = f"{len(w.items)} things in view"

        with self._stage("predict") as p:
            for sig in signals:
                for key, raw in sig.features.items():
                    w.perceive(key, raw, now)
            w.check_expectations([e for s in signals for e in s.events], now)
            p["note"] = f"{len(w.surprises)} surprise(s)" if w.surprises else "as predicted"

        with self._stage("attend") as p:
            need = w.needs_vectors()
            if need:
                try:
                    vecs = await asyncio.to_thread(self.embedder, [t for _, t in need])
                    w.set_vectors(zip([k for k, _ in need], vecs))
                except Exception as exc:
                    log.warning("[loop] embedding failed: %s", exc)
            w.capture()
            w.layout()
            w.fit(now)
            p["note"] = (f"pulled to {w.pulled['by']}" if w.pulled else f"on {w.focus_label()} ({w.dwell})") + \
                        (f" · {len(w.faded)} faded" if w.faded else "")

        with self._stage("feel") as p:
            mood = w.compute_mood(self.budget.energy, now)
            p["note"] = mood["word"]

        with self._stage("render") as p:
            header = {"part_of_day": part_of_day(datetime.fromtimestamp(now, timezone.utc).hour),
                      "woke": self._woke_line(gap), "energy": self.budget.energy,
                      "tokens_left": f"{self.budget.tokens_left:,}"}
            view = w.render(now, header)
            p["note"] = f"{len(view)} chars"

        self.phase = "thinking"
        result = await self._think(view)

        with self._stage("guard") as p:
            notes = []
            if result.get("error"):
                self.error_streak += 1
                self.last_error = str(result["error"])
                self.event("error", _clip(self.last_error, 200))
            else:
                self.error_streak = 0
                fp = fingerprint(result)
                self.stale_streak = self.stale_streak + 1 if self._fingerprints and self._fingerprints[-1] == fp else 0
                self._fingerprints.append(fp)
            if c.stale_streak_limit and self.stale_streak >= c.stale_streak_limit:
                self.guard_rests += 1
                self.stale_streak = 0
                if self.guard_rests > c.max_guard_rests:
                    self.request_stop(f"guard: still repeating after {c.max_guard_rests} forced rests")
                else:
                    self.request_rest(c.guard_rest_minutes, "guard: you kept repeating yourself")
                    w.upsert("guard-rest", "alert", "body", "you caught yourself repeating and were made to step away",
                             gist="made to step away", salience=0.7, valence=-0.2)
                notes.append("repetition")
            if c.error_streak_limit and self.error_streak >= c.error_streak_limit:
                self.request_stop(f"guard: {self.error_streak} errors in a row")
                notes.append("errors")
            if result.get("tokens", 0) > c.max_tokens_per_tick:
                notes.append("tick token cap")
            for n in notes:
                self.event("guard", n)
            p["note"] = ", ".join(notes) or "clear"

        with self._stage("record"):
            self.budget.spend(result.get("tokens", 0), result.get("cost", 0.0))
            self.session_ticks += 1
            self.session_tokens += result.get("tokens", 0)
            self.session_cost += result.get("cost", 0.0)
            self.last_tick_at = now
            self.last_result = {
                "tokens": result.get("tokens", 0), "latency": result.get("latency", 0.0),
                "error": result.get("error"),
                "tools": [{"tool": t["tool"], "ok": t["ok"]} for t in result.get("tool_calls", [])],
            }
            view_head = "\n".join(view.splitlines()[:3])
            if result.get("response"):
                self.history.append({"view": view_head, "response": result["response"][:2000]})
                self.history = self.history[-max(1, c.history_window):]
            entry = {
                "tick": w.tick, "time": _iso(now), "agent": c.agent, "model": result.get("model", ""),
                "wake": self.wake_reason, "focus": w.focus_label(), "mood": w.mood.get("word"),
                "view": view, "view_head": view_head,
                "response": (result.get("response") or "")[:5000],
                "tool_calls": result.get("tool_calls", []),
                "tokens": result.get("tokens", 0), "cost": round(result.get("cost", 0.0), 6),
                "latency": round(result.get("latency", 0.0), 2), "steps": result.get("steps", 0),
                "error": result.get("error"),
                "surprises": w.surprises, "pulled": w.pulled, "faded": w.faded,
            }
            self.ticks.append(entry)
            self.journal.append({
                "ts": entry["time"], "tick": w.tick, "agent": c.agent, "model": entry["model"],
                "focus": w.focus_label(), "mood": w.mood.get("word"), "narrative": narrate(result),
                "tools_used": [t["tool"] for t in result.get("tool_calls", [])],
                "tokens": entry["tokens"], "cost": entry["cost"], "had_error": bool(result.get("error")),
            })
            if w.pulled:
                self.event("pull", f"attention pulled to {w.pulled['to']} by {w.pulled['by']}")
            for s in w.surprises:
                self.event("surprise", f"({s['source']}) {s['text']}")
            for g in w.faded:
                self.event("fade", g)
            self.save()

    async def _think(self, view: str) -> dict:
        c = self.config
        result: Dict[str, Any] = {"response": "", "tool_calls": [], "tokens": 0, "cost": 0.0,
                                  "model": "", "latency": 0.0, "steps": 0}
        t0 = time.perf_counter()
        with self._stage("think") as p:
            try:
                system, registry_tools = await asyncio.to_thread(self.host.prepare, c.agent, view)
                system = [dict(m) for m in system] or [{"role": "system", "content": ""}]
                system[0]["content"] = (system[0].get("content") or "").rstrip() + "\n\n" + LOOP_PREAMBLE
                own = set(self.tools.names())
                tool_defs = [t for t in registry_tools
                             if t["function"]["name"] not in EXCLUDED_TOOLS | own] + self.tools.definitions()

                messages: List[dict] = list(system)
                for h in self.history[-c.history_window:] if c.history_window > 0 else []:
                    messages += [{"role": "user", "content": h["view"] or "(an earlier moment)"},
                                 {"role": "assistant", "content": h["response"]}]
                messages.append({"role": "user", "content": view})

                calls = 0
                for step in range(c.max_steps_per_tick + 1):
                    comp = await self.host.complete(c, messages, tool_defs)
                    result["steps"] = step + 1
                    result["tokens"] += comp.tokens
                    result["cost"] += comp.cost
                    result["model"] = comp.model or result["model"]
                    msg = comp.message or {}
                    tcs = msg.get("tool_calls") or []
                    can_continue = step < c.max_steps_per_tick and result["tokens"] < c.max_tokens_per_tick
                    if tcs and can_continue:
                        messages.append(msg)
                        for tc in tcs:
                            fn = tc.get("function") or {}
                            name = fn.get("name", "")
                            raw = fn.get("arguments") or "{}"
                            try:
                                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
                            except (json.JSONDecodeError, TypeError, ValueError):
                                args = {}
                            if calls >= c.max_tool_calls_per_tick:
                                out, ok, ms = "Skipped: you've reached this tick's tool-call limit.", False, 0.0
                            else:
                                calls += 1
                                out, ok, ms = await self._call_tool(name, args)
                            result["tool_calls"].append({"tool": name, "arguments": args, "result": out[:2000],
                                                         "ok": ok, "ms": ms})
                            messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": out[:8000]})
                        continue
                    text = msg.get("content") or ""
                    if tcs and not text:
                        text = "(stopped mid-action: step or token limit for this tick reached)"
                    result["response"] = await asyncio.to_thread(self.host.after_response, c.agent, text)
                    break
                p["note"] = f"{result['steps']} step(s) · {result['tokens']:,} tok · {len(result['tool_calls'])} tool call(s)"
            except Exception as exc:
                log.warning("[loop] think failed: %s", exc)
                result["error"] = str(exc)
                p["note"] = f"error: {_clip(str(exc), 80)}"
                p["errors"] += 1
        if result.get("error"):
            self.processes["think"]["status"] = "error"
        result["latency"] = time.perf_counter() - t0
        return result

    async def _call_tool(self, name: str, args: dict) -> Tuple[str, bool, float]:
        t0 = time.perf_counter()
        with self._stage("act") as p:
            try:
                seen = False
                if name in self.tools.handlers:
                    out = self.tools.execute(name, args)
                    seen = name == "workbench" and args.get("action") in ("read", "list", "reflections")
                elif name in EXCLUDED_TOOLS:
                    out = f"Error: '{name}' isn't available inside the loop."
                else:
                    out = await asyncio.to_thread(self.host.call_tool, self.config.agent, name, args)
                    seen = True
            except PermissionError as exc:
                out = f"BLOCKED: {exc}"
            except KeyError:
                out = f"Error: unknown tool '{name}'"
            except Exception as exc:
                out = f"Error: {exc}"
            out = out if isinstance(out, str) else json.dumps(out, default=str)
            lowered = out[:200].lower()
            ok = not (out.startswith(("Error", "BLOCKED", "Skipped")) or '"ok": false' in lowered)
            if seen and ok:
                self.world.see(name, args, out)
            p["note"] = f"{name} → {'ok' if ok else 'failed'}"
        return out, ok, round((time.perf_counter() - t0) * 1000, 1)
