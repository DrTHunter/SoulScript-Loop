"""StandaloneHost and build_loop: run the loop without any web app.

The daemon needs a Host: something that builds the persona prompt, calls the
model, and runs tools beyond the loop's own. This one uses a fixed (or
retrieved) system prompt, any OpenAI-compatible backend, and a ToolRegistry.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .backend import Backend, Completion, OpenAICompatibleBackend, backend_from_config
from .config import LoopConfig
from .daemon import LoopDaemon
from .embedding import Embedder, HashEmbedder, SentenceEmbedder
from .machine import machine_from_config
from .registry import ToolRegistry
from .sandbox import RunPythonTool, sandbox_from_config

log = logging.getLogger(__name__)

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
        self._side: dict = {}

    def soul(self) -> str:
        """Her identity. A retrieval function wins; then the soul_script file (read fresh every tick, so
        you can edit her while she runs); then the inline system_prompt. All empty is a valid answer: she
        is then only the loop."""
        path = (self.config.soul_script or "").strip()
        if path:
            try:
                return Path(path).expanduser().read_text(encoding="utf-8").strip()
            except OSError as exc:
                log.warning("[loop] soul_script %s unreadable: %s", path, exc)
        return self.config.system_prompt or ""

    def prepare(self, agent: str, view: str) -> Tuple[List[dict], List[dict]]:
        prompt = self.identity(agent, view) if self.identity else self.soul()
        return [{"role": "system", "content": prompt or ""}], self.tools.definitions()

    async def side_complete(self, name: str, messages: List[dict], max_tokens: int) -> Completion:
        """The llm tool's model: its own settings, falling back to the main backend's connection."""
        models = (self.config.llm or {}).get("models") or {}
        spec = models[name]
        if name not in self._side:
            main = self.config.backend or {}
            opts = {k: main[k] for k in ("base_url", "temperature", "price_in_per_mtok", "price_out_per_mtok",
                                         "prompt_cache") if k in main}
            opts.update({k: v for k, v in spec.items() if k not in ("model", "api_key_env")})
            key_env = spec.get("api_key_env") or main.get("api_key_env")
            self._side[name] = OpenAICompatibleBackend(
                model=spec["model"], api_key=os.environ.get(key_env) if key_env else None, **opts)
        return await self._side[name].complete(messages, [], max_tokens)

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
    machine = machine_from_config(config.machine)
    if machine:
        machine.register(tools)
    host = StandaloneHost(config, backend or backend_from_config(config.backend), tools, identity, tasks)
    daemon = LoopDaemon(host, config, Path(config.data_dir), embedder=embedder or make_embedder(config.embedder))
    daemon.machine = machine
    return daemon


__all__ = ["IdentityBuilder", "StandaloneHost", "build_loop", "make_embedder"]
