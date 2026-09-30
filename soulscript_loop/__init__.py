"""SoulScript Loop — a continuously ticking inner loop for a single AI persona.

Extracted from the OrionForge AGI loop. Each tick the runner senses
(time, budget, inbox, last tick, repetition), builds a stimulus the
persona cannot author, sends it through an LLM with tools, and records
the result. Safety guards stop or pause the loop on repetition, cost
overruns, and error streaks.
"""

from .backend import Backend, Completion, EchoBackend, OpenAICompatibleBackend
from .config import LoopConfig
from .runner import LoopRunner
from .senses import DEFAULT_SENSES, Sense
from .state import LoopState
from .tools import LoopControlTool, ToolRegistry
from .workbench import Workbench

__all__ = [
    "Backend",
    "Completion",
    "DEFAULT_SENSES",
    "EchoBackend",
    "LoopConfig",
    "LoopControlTool",
    "LoopRunner",
    "LoopState",
    "OpenAICompatibleBackend",
    "Sense",
    "ToolRegistry",
    "Workbench",
]

__version__ = "0.1.0"
