"""SoulScript Loop — a continuously running perceptual field for one AI persona.

    channels   → signals she can't author: time, energy, the feel of her last action,
                 messages and tasks at the door, changes to her bench
    prediction → a belief per signal; the error becomes surprise; surprise drives learning
    world      → the field: focus on anything, everything else arranged by relatedness,
                 HUD gauges, alerts, fading, finite capacity, mood read off the field
    embedding  → relatedness (MiniLM if installed, a hashed fallback otherwise)
    daemon     → wall-time process woken by messages: sense → update → predict → attend →
                 feel → render → think/act → guard → record → sleep
    tools      → attend, reply, loop_control, workbench (the loop's own tools)
    host       → StandaloneHost + build_loop: run it with any OpenAI-compatible model
"""

from .backend import Backend, Completion, EchoBackend, OpenAICompatibleBackend, backend_from_config
from .config import LoopConfig
from .daemon import Host, LoopDaemon
from .embedding import HashEmbedder, SentenceEmbedder
from .host import StandaloneHost, build_loop
from .registry import ToolRegistry
from .workbench import Workbench
from .world import InnerWorld

__all__ = [
    "Backend",
    "Completion",
    "EchoBackend",
    "HashEmbedder",
    "Host",
    "InnerWorld",
    "LoopConfig",
    "LoopDaemon",
    "OpenAICompatibleBackend",
    "SentenceEmbedder",
    "StandaloneHost",
    "ToolRegistry",
    "Workbench",
    "backend_from_config",
    "build_loop",
]

__version__ = "0.2.0"
