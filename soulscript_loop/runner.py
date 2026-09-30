"""The loop itself: sense → stimulus → model + tools → record → guard → repeat."""

import asyncio
import hashlib
import inspect
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, List, Optional, Union

from .backend import Backend
from .config import LoopConfig
from .senses import DEFAULT_INSTRUCTIONS, DEFAULT_SENSES, Sense, SenseContext, build_stimulus
from .sandbox import DockerSandbox, RunPythonTool, sandbox_from_config
from .state import LoopState
from .tools import LoopControlTool, ToolRegistry
from .workbench import Workbench

log = logging.getLogger(__name__)

# (stimulus, prior history) -> messages sent to the model.
# Swap this out to re-anchor identity every tick, e.g. with SoulScript Engine retrieval.
ContextBuilder = Callable[[str, List[dict]], Union[List[dict], Awaitable[List[dict]]]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Tick journal & staleness ──────────────────────────────────────

def build_tick_narrative(tick_result: dict) -> str:
    """Build a short human-readable narrative from a tick result."""
    if tick_result.get("error"):
        return f"Encountered an error: {str(tick_result['error'])[:500]}"

    parts: List[str] = []
    tools = tick_result.get("tool_calls", [])
    if tools:
        names = list(dict.fromkeys(tc.get("tool", "unknown") for tc in tools))
        if len(names) == 1:
            parts.append(f"Used {names[0]}.")
        else:
            parts.append(f"Used {', '.join(names[:-1])} and {names[-1]}.")

    # Response excerpt — first 4 sentences or first 600 chars
    response = (tick_result.get("response") or "").strip()
    if response:
        sentences = response.replace("\n", " ").split(". ")
        excerpt = ". ".join(sentences[:4])
        if not excerpt.endswith("."):
            excerpt += "."
        if len(excerpt) > 600:
            excerpt = excerpt[:597] + "..."
        parts.append(excerpt)
    else:
        parts.append("No textual response returned.")

    return " ".join(parts)


def compute_tick_fingerprint(tick_result: dict) -> str:
    """Normalized fingerprint of a tick's tool calls + response.

    Captures *what* the agent did (tool names + short arg values) and a
    trimmed, lowered version of the response. Two ticks with the same
    fingerprint are considered duplicates.
    """
    parts: List[str] = []
    for tc in tick_result.get("tool_calls", []):
        args = tc.get("arguments", {}) or {}
        arg_vals = [f"{k}={str(args[k])[:80]}" for k in sorted(args)]
        parts.append(f"{tc.get('tool', '')}({','.join(arg_vals)})")

    resp = (tick_result.get("response") or "").strip().lower()
    parts.append(" ".join(resp.split())[:500])
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# ── Runner ────────────────────────────────────────────────────────

class LoopRunner:
    def __init__(
        self,
        config: LoopConfig,
        backend: Backend,
        tools: Optional[ToolRegistry] = None,
        senses: Optional[List[Sense]] = None,
        context_builder: Optional[ContextBuilder] = None,
        instructions: str = DEFAULT_INSTRUCTIONS,
        state: Optional[LoopState] = None,
    ):
        self.config = config
        self.backend = backend
        self.state = state or LoopState(config.data_dir)
        self.tools = tools or ToolRegistry()
        LoopControlTool(self.state).register(self.tools)
        self.senses = list(DEFAULT_SENSES if senses is None else senses)
        self.workbench: Optional[Workbench] = None
        if config.workbench:
            self.workbench = Workbench(Path(config.data_dir) / "workbench")
            self.workbench.register(self.tools)
            self.senses.append(self.workbench.sense)
        self.sandbox: Optional[DockerSandbox] = None
        if self.workbench and config.sandbox.get("enabled"):
            self.sandbox = sandbox_from_config(config.sandbox, self.workbench.root)
            if self.sandbox:
                RunPythonTool(self.sandbox).register(self.tools)
        self.context_builder = context_builder or self._default_context
        self.instructions = instructions
        # Rebuild conversational continuity from what survived on disk.
        self.history: List[dict] = []
        for t in self.state.tick_history:
            if t.get("stimulus") and t.get("response"):
                self.history += [
                    {"role": "user", "content": t["stimulus"]},
                    {"role": "assistant", "content": t["response"]},
                ]

    # ── Public controls ───────────────────────────────────────────

    def start(self) -> asyncio.Task:
        """Start the loop as a background task on the running event loop."""
        if self.state.running:
            raise RuntimeError("Loop already running")
        self.state.task = asyncio.create_task(self.run())
        return self.state.task

    def stop(self, reason: str = "operator_stop"):
        self.state.running = False
        self.state.stop_reason = reason
        if self.state.task and not self.state.task.done():
            self.state.task.cancel()

    def pause(self):
        self.state.paused = True

    def resume(self):
        self.state.paused = False

    def post_message(self, text: str, sender: str = "user"):
        """Drop a message into an already-running mind. It surfaces on the next tick's inbox sense."""
        self.state.inbox.append({"sender": sender, "text": text, "received_at": _now_iso()})

    # ── One tick ──────────────────────────────────────────────────

    def _default_context(self, stimulus: str, history: List[dict]) -> List[dict]:
        messages: List[dict] = []
        if self.config.system_prompt:
            messages.append({"role": "system", "content": self.config.system_prompt})
        window = self.config.history_window
        messages += history[-window:] if window > 0 else []
        messages.append({"role": "user", "content": stimulus})
        return messages

    async def execute_tick(self, stimulus: str) -> dict:
        """Send one stimulus through the model, running tool calls up to the step limit."""
        try:
            messages = self.context_builder(stimulus, self.history)
            if inspect.isawaitable(messages):
                messages = await messages
            running = list(messages)
            tool_defs = self.tools.definitions()

            max_steps = self.config.max_steps_per_tick
            max_tool_calls = self.config.max_tool_calls_per_tick
            tool_call_log: List[dict] = []
            total_cost = 0.0
            total_tool_calls = 0
            model = ""
            response_text = ""

            for step in range(max_steps + 1):
                completion = await self.backend.complete(running, tool_defs)
                total_cost += completion.cost
                model = completion.model or model
                msg = completion.message
                tool_calls = msg.get("tool_calls")

                if (completion.finish_reason == "tool_calls" or tool_calls) and step < max_steps:
                    running.append(msg)
                    for tc in tool_calls or []:
                        if total_tool_calls >= max_tool_calls:
                            log.warning("[tick] hit max_tool_calls (%d) — skipping remaining", max_tool_calls)
                            break
                        fn = tc.get("function", {})
                        name = fn.get("name", "")
                        raw = fn.get("arguments", "{}")
                        try:
                            args = json.loads(raw) if isinstance(raw, str) else (raw or {})
                        except json.JSONDecodeError:
                            args = {}

                        total_tool_calls += 1
                        log.info("[tick] calling %s(%s) [%d/%d]", name, args, total_tool_calls, max_tool_calls)
                        try:
                            result = await self.tools.execute(name, args)
                        except PermissionError as exc:
                            result = f"BLOCKED: {exc}"
                        except Exception as exc:
                            result = f"Error: {exc}"

                        tool_call_log.append({"tool": name, "arguments": args, "result": result[:2000]})
                        running.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": result})
                    continue

                response_text = msg.get("content") or ""
                break

            self.history += [
                {"role": "user", "content": stimulus},
                {"role": "assistant", "content": response_text},
            ]
            return {"response": response_text, "tool_calls": tool_call_log, "cost": total_cost, "model": model}

        except Exception as exc:
            log.error("[tick] Tick failed: %s", exc)
            return {"error": str(exc), "response": "", "cost": 0.0, "tool_calls": []}

    # ── The loop ──────────────────────────────────────────────────

    async def _sleep_while_running(self, seconds: float):
        end = time.monotonic() + seconds
        while self.state.running and time.monotonic() < end:
            await asyncio.sleep(min(1.0, end - time.monotonic()))

    async def run(self):
        """Drive the loop until a guard, the agent, or the operator stops it."""
        state, config = self.state, self.config
        task, inbox = state.task, state.inbox
        state.reset_session()
        state.task, state.inbox = task, inbox
        state.running = True
        state.started_at = _now_iso()
        loop_count = 0

        try:
            while state.running:
                loop_count += 1
                state.current_loop = loop_count
                if config.max_loops > 0 and loop_count > config.max_loops:
                    state.stop_reason = "max_loops_reached"
                    break

                for tick in range(1, config.ticks_per_loop + 1):
                    # Pause gate
                    if state.paused:
                        log.info("[loop] Paused — waiting for resume")
                        while state.paused and state.running:
                            await asyncio.sleep(0.25)
                    if not state.running:
                        break

                    state.current_tick = tick
                    state.total_ticks += 1
                    tick_mono = time.monotonic()

                    # Sense → stimulus. Inbox is consumed by this tick.
                    if config.stimulus:
                        stim = config.stimulus
                    else:
                        ctx = SenseContext(state, config, datetime.now(timezone.utc), tick_mono, tick, loop_count)
                        stim = build_stimulus(ctx, self.senses, self.instructions)
                    delivered = list(state.inbox)
                    state.inbox.clear()

                    tick_result = await self.execute_tick(stim)
                    state.last_tick_at = tick_mono

                    tick_cost = tick_result.get("cost", 0.0)
                    state.session_cost += tick_cost
                    state.total_cost += tick_cost

                    if tick_result.get("error"):
                        state.error_streak += 1
                        state.last_error = tick_result["error"]
                        # Undelivered messages go back in the inbox for the next tick.
                        state.inbox[:0] = delivered
                    else:
                        state.error_streak = 0

                    state.log_tick({
                        "loop": loop_count,
                        "tick": tick,
                        "time": _now_iso(),
                        "agent": config.agent,
                        "stimulus": stim[:2000],
                        "response": tick_result.get("response", "")[:5000],
                        "tool_calls": tick_result.get("tool_calls", []),
                        "cost": tick_cost,
                        "error": tick_result.get("error"),
                        "model": tick_result.get("model", ""),
                    })
                    state.log_journal({
                        "ts": _now_iso(),
                        "loop": loop_count,
                        "tick": tick,
                        "agent": config.agent,
                        "model": tick_result.get("model", ""),
                        "narrative": build_tick_narrative(tick_result),
                        "tools_used": [tc.get("tool", "") for tc in tick_result.get("tool_calls", [])],
                        "cost": round(tick_cost, 6),
                        "had_error": bool(tick_result.get("error")),
                    })

                    # ── Guards ────────────────────────────────────
                    if not tick_result.get("error"):
                        if state.record_fingerprint(compute_tick_fingerprint(tick_result)):
                            log.warning("[loop] Stale tick detected (streak %d/%d)",
                                        state.stale_streak, config.stale_streak_limit)
                        if config.stale_streak_limit and state.stale_streak >= config.stale_streak_limit:
                            state.running = False
                            state.stop_reason = "stale_streak_exceeded"
                            break

                    if config.auto_pause_on_budget:
                        if config.per_tick_cap and tick_cost > config.per_tick_cap:
                            state.paused = True
                            state.stop_reason = "per_tick_budget_exceeded"
                            log.warning("[loop] Per-tick budget exceeded ($%.4f > $%.4f) — paused",
                                        tick_cost, config.per_tick_cap)
                            break
                        if config.per_session_cap and state.session_cost > config.per_session_cap:
                            state.running = False
                            state.stop_reason = "session_budget_exceeded"
                            break

                    if config.auto_pause_on_error_streak and state.error_streak >= config.auto_pause_on_error_streak:
                        state.running = False
                        state.stop_reason = "error_streak_exceeded"
                        break

                    if config.tick_interval_seconds > 0:
                        await self._sleep_while_running(config.tick_interval_seconds)

                if state.running and not state.paused and config.loop_interval_seconds > 0:
                    log.info("[loop] Waiting %ds before next loop", config.loop_interval_seconds)
                    await self._sleep_while_running(config.loop_interval_seconds)

        except asyncio.CancelledError:
            state.stop_reason = state.stop_reason or "cancelled"
        except Exception as exc:
            state.stop_reason = f"exception: {exc}"
            log.error("[loop] Runner crashed: %s", exc)
        finally:
            state.running = False
            state.stopped_at = _now_iso()
            log.info("[loop] Stopped — reason: %s, total ticks: %d, cost: $%.4f",
                     state.stop_reason, state.total_ticks, state.total_cost)
