"""Model backends. Anything with ``async complete(messages, tools)`` works."""

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


class Backend(Protocol):
    async def complete(self, messages: List[dict], tools: List[dict]) -> Completion: ...


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

    async def complete(self, messages: List[dict], tools: List[dict]) -> Completion:
        import httpx

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
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
        return Completion(
            message=choice.get("message") or {},
            finish_reason=choice.get("finish_reason") or "stop",
            usage=usage,
            cost=cost,
            model=data.get("model", self.model),
        )


class EchoBackend:
    """Offline backend for demos and tests: reflects the stimulus back, costs nothing."""

    model = "echo"

    async def complete(self, messages: List[dict], tools: List[dict]) -> Completion:
        last = next((m for m in reversed(messages) if m.get("role") == "user"), {})
        first_line = (last.get("content") or "").splitlines()[0] if last.get("content") else ""
        return Completion(
            message={"role": "assistant", "content": f"Sensed: {first_line}"},
            model=self.model,
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
