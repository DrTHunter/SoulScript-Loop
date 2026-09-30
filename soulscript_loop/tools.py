"""Tool registry and the built-in loop_control tool."""

import inspect
import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Tuple, Union

from .state import LoopState

log = logging.getLogger(__name__)

ToolHandler = Callable[[dict], Union[str, Awaitable[str]]]


class ToolRegistry:
    """Maps tool names to (definition, handler).

    Definitions use the plain ``{name, description, parameters}`` shape
    and are wrapped into OpenAI function-calling format on export.
    """

    def __init__(self):
        self._tools: Dict[str, Tuple[dict, ToolHandler]] = {}

    def register(self, definition: dict, handler: ToolHandler):
        self._tools[definition["name"]] = (definition, handler)

    def definitions(self) -> List[dict]:
        return [{"type": "function", "function": d} for d, _ in self._tools.values()]

    async def execute(self, name: str, arguments: dict) -> str:
        if name not in self._tools:
            return f"Error: unknown tool '{name}'"
        _, handler = self._tools[name]
        result = handler(arguments)
        if inspect.isawaitable(result):
            result = await result
        return result if isinstance(result, str) else json.dumps(result, default=str)


class LoopControlTool:
    """Lets the persona inspect and steer its own loop — including stopping it."""

    def __init__(self, state: LoopState):
        self.state = state

    @staticmethod
    def definition() -> dict:
        return {
            "name": "loop_control",
            "description": (
                "Query or control your own autonomous loop. "
                "Actions: "
                "'status' — get current loop state, tick count, cost, errors; "
                "'tick_history' — get recent tick results with optional limit; "
                "'request_pause' — pause the loop after the current tick; "
                "'request_resume' — resume from pause; "
                "'request_stop' — gracefully stop the loop entirely. Use this when "
                "you have completed all available tasks, are stuck in a repetitive "
                "cycle, or determine that continued execution is unproductive. "
                "Provide a reason so the operator knows why you stopped."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "status",
                            "tick_history",
                            "request_pause",
                            "request_resume",
                            "request_stop",
                        ],
                        "description": "The action to perform.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max tick history entries to return (default 10).",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for stopping or pausing. Required for request_stop.",
                    },
                },
                "required": ["action"],
            },
        }

    def execute(self, arguments: dict) -> str:
        action = arguments.get("action", "status")
        state = self.state

        if action == "status":
            return json.dumps(state.to_dict(), indent=2, default=str)

        elif action == "tick_history":
            limit = arguments.get("limit", 10)
            return json.dumps({
                "ticks": state.tick_history[-limit:],
                "total_recorded": len(state.tick_history),
            }, indent=2, default=str)

        elif action == "request_pause":
            if not state.running:
                return json.dumps({"ok": False, "reason": "Loop is not running"})
            state.paused = True
            return json.dumps({
                "ok": True,
                "message": "Pause requested — loop will pause after current tick",
            })

        elif action == "request_resume":
            if not state.paused:
                return json.dumps({"ok": False, "reason": "Loop is not paused"})
            state.paused = False
            return json.dumps({"ok": True, "message": "Loop resumed"})

        elif action == "request_stop":
            reason = arguments.get("reason", "Agent requested stop")
            if not state.running:
                return json.dumps({"ok": False, "reason": "Loop is not running"})
            state.running = False
            state.stop_reason = f"agent_requested: {reason}"
            log.info("[loop] Agent requested stop: %s", reason)
            return json.dumps({
                "ok": True,
                "message": f"Stop requested — loop will end after current tick. Reason: {reason}",
            })

        return json.dumps({"error": f"Unknown action: {action}"})

    def register(self, registry: ToolRegistry):
        registry.register(self.definition(), self.execute)
