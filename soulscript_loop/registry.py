"""Registry for your own tools (anything beyond the loop's built-ins)."""

import inspect
import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Tuple, Union


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
