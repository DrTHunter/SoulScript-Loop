"""StandaloneHost and build_loop: run the loop without any web app.

The daemon needs a Host: something that builds the persona prompt, calls the
model, and runs tools beyond the loop's own. This one uses a fixed (or
retrieved) system prompt, any OpenAI-compatible backend, and a ToolRegistry.
"""

import asyncio
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .backend import Backend, Completion, backend_from_config
from .config import LoopConfig
from .daemon import LoopDaemon
from .embedding import Embedder, HashEmbedder, SentenceEmbedder
from .registry import ToolRegistry
from .sandbox import RunPythonTool, sandbox_from_config

# (agent, current view) -> system prompt. Plug SoulScript Engine retrieval in here
# to re-anchor identity every tick with the soul-script sections relevant to what she sees.
IdentityBuilder = Callable[[str, str], str]


class StandaloneHost:
    def __init__(
        self,
        config: LoopConfig,
        backend: Backend,
        tools: Optional[ToolRegistry] = None,
        identity: Optional[IdentityBuilder] = None,
        tasks: Optional[Callable[[], List[dict]]] = None,
    ):
        self.config = config
        self.backend = backend
        self.tools = tools or ToolRegistry()
        self.identity = identity
        self.tasks = tasks

    def prepare(self, agent: str, view: str) -> Tuple[List[dict], List[dict]]:
        prompt = self.identity(agent, view) if self.identity else self.config.system_prompt
        return [{"role": "system", "content": prompt or ""}], self.tools.definitions()

    async def complete(self, config: LoopConfig, messages: List[dict], tools: List[dict]) -> Completion:
        return await self.backend.complete(messages, tools)

    def call_tool(self, agent: str, name: str, args: dict) -> str:
        # Runs in a worker thread; async tool handlers get their own event loop here.
        return asyncio.run(self.tools.execute(name, args))

    def after_response(self, agent: str, text: str) -> str:
        return text

    def pending_tasks(self) -> List[dict]:
        """Tasks shown at the door: dicts with id, task, priority, from. Resolved when they stop appearing."""
        return list(self.tasks()) if self.tasks else []


def make_embedder(kind: str) -> Embedder:
    if kind == "hash":
        return HashEmbedder()
    return SentenceEmbedder()   # "minilm" and "auto" — falls back to hashing if sentence-transformers is missing


def build_loop(
    config: LoopConfig,
    backend: Optional[Backend] = None,
    tools: Optional[ToolRegistry] = None,
    identity: Optional[IdentityBuilder] = None,
    tasks: Optional[Callable[[], List[dict]]] = None,
    embedder: Optional[Embedder] = None,
) -> LoopDaemon:
    """Wire a ready-to-start LoopDaemon from a config."""
    tools = tools or ToolRegistry()
    if config.workbench and config.sandbox.get("enabled"):
        sandbox = sandbox_from_config(config.sandbox, Path(config.data_dir) / "workbench")
        if sandbox:
            RunPythonTool(sandbox).register(tools)
    host = StandaloneHost(config, backend or backend_from_config(config.backend), tools, identity, tasks)
    return LoopDaemon(host, config, Path(config.data_dir), embedder=embedder or make_embedder(config.embedder))


__all__ = ["IdentityBuilder", "StandaloneHost", "build_loop", "make_embedder"]
