"""Model backends. Anything with ``async complete(messages, tools)`` works."""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class Completion:
    message: Dict[str, Any]              # assistant message, may carry tool_calls
    finish_reason: str = "stop"
    usage: Dict[str, Any] = field(default_factory=dict)
    cost: float = 0.0
    model: str = ""
    tokens: int = 0                      # spent from the daily energy budget
    prompt_tokens: int = 0
    cached_tokens: int = 0               # prompt tokens the provider served from its prefix cache


class Backend(Protocol):
    async def complete(self, messages: List[dict], tools: List[dict]) -> Completion: ...


def wire_messages(messages: List[dict], prompt_cache: bool) -> List[dict]:
    """The loop marks cache breakpoints with ``"cache": True`` on a message. No server wants that key,
    so it is always stripped; with ``prompt_cache`` on it becomes ``cache_control`` on the message's last
    text block (the form Claude and Gemini take through OpenRouter and compatible gateways)."""
    out = []
    for m in messages:
        m = dict(m)
        marked = m.pop("cache", False)
        content = m.get("content")
        if prompt_cache and marked and isinstance(content, str) and content:
            m["content"] = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
        out.append(m)
    return out


class OpenAICompatibleBackend:
    """Any ``/chat/completions`` endpoint: OpenAI, OpenRouter, DeepSeek, Ollama, LM Studio, vLLM.

    Cost is estimated from token usage and the per-million-token prices
    you configure (leave at 0 for local models).
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: Optional[str] = None,
        temperature: float = 0.7,
        timeout: float = 120.0,
        price_in_per_mtok: float = 0.0,
        price_out_per_mtok: float = 0.0,
        prompt_cache: bool = False,
        max_tokens: int = 0,
    ):
        url = base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        self.url = url
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self.price_in = price_in_per_mtok
        self.price_out = price_out_per_mtok
        self.prompt_cache = prompt_cache
        self.max_tokens = max_tokens

    async def complete(self, messages: List[dict], tools: List[dict], max_tokens: int = 0) -> Completion:
        import httpx

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": wire_messages(messages, self.prompt_cache),
            "temperature": self.temperature,
        }
        cap = max_tokens or self.max_tokens
        if cap:
            payload["max_tokens"] = cap
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.url, json=payload, headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code} from {self.url}: {resp.text[:1000]}")
            data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        cost = (
            usage.get("prompt_tokens", 0) * self.price_in
            + usage.get("completion_tokens", 0) * self.price_out
        ) / 1_000_000
        message = choice.get("message") or {}
        tokens = usage.get("total_tokens") or (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0))
        if not tokens:  # some local servers omit usage; estimate so energy still drains
            tokens = (len(json.dumps(messages)) + len(json.dumps(message))) // 4
        return Completion(
            message=message,
            finish_reason=choice.get("finish_reason") or "stop",
            usage=usage,
            cost=cost,
            model=data.get("model", self.model),
            tokens=int(tokens),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            cached_tokens=int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
        )


class EchoBackend:
    """Offline backend for demos and tests: reports its focus back, costs nothing (but still tires)."""

    model = "echo"

    async def complete(self, messages: List[dict], tools: List[dict], max_tokens: int = 0) -> Completion:
        last = next((m for m in reversed(messages) if m.get("role") == "user"), {})
        lines = (last.get("content") or "").splitlines()
        focus = next((ln for ln in lines if ln.startswith("FOCUS")), lines[0] if lines else "")
        return Completion(
            message={"role": "assistant", "content": f"I see it. {focus}"},
            model=self.model,
            tokens=sum(len(m.get("content") or "") for m in messages) // 4,
        )


def backend_from_config(cfg: Dict[str, Any]) -> Backend:
    kind = cfg.get("type", "openai")
    if kind == "echo":
        return EchoBackend()
    if kind == "openai":
        opts = {k: v for k, v in cfg.items() if k not in ("type", "api_key_env")}
        if cfg.get("api_key_env"):
            opts["api_key"] = os.environ.get(cfg["api_key_env"])
        return OpenAICompatibleBackend(**opts)
    raise ValueError(f"Unknown backend type: {kind}")
