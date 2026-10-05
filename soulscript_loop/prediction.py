"""Predictive processing: top-down expectations, bottom-up error, surprise.

Every channel feature carries a running belief (mean + variance, or a
probability for yes/no events). Each tick the observation is compared
to the belief; the mismatch becomes surprise in [0, 1]. Surprise both
raises the learning rate (the belief moves further) and is handed to
the world model, where it becomes salience and can capture attention.

Agent-authored expectations are the other top-down path: the agent says
"I expect X at the door within 30 minutes", and the world checks it.
"""

import math
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional


@dataclass(frozen=True)
class FeatureSpec:
    kind: str              # "gauss" (continuous, log-scaled) | "bern" (did it happen)
    source: str            # where a surprise on this feature comes from
    more: str              # text when the observation is above expectation
    less: str              # text when it is below
    unit: str = ""         # "s" | "tok" | ""


FEATURES: Dict[str, FeatureSpec] = {
    "time.gap": FeatureSpec(
        "gauss", "time",
        "more time passed than you expected", "you woke sooner than you expected", "s"),
    "body.burn": FeatureSpec(
        "gauss", "body",
        "your last thought cost more than you expected", "your last thought was lighter than you expected", "tok"),
    "body.latency": FeatureSpec(
        "gauss", "body",
        "thinking took longer than usual", "thinking came quicker than usual", "s"),
    "body.tool_fail": FeatureSpec(
        "bern", "body",
        "a tool failed when you expected it to work", "your tools worked when you expected trouble"),
    "door.arrival": FeatureSpec(
        "bern", "door",
        "something came through the door when you didn't expect it",
        "the door stayed quiet when you expected someone"),
    "bench.outside_change": FeatureSpec(
        "bern", "bench",
        "someone changed the bench while you were away", ""),
}

SURPRISE_FLOOR = 0.25      # below this, the error is absorbed silently
WARMUP = 3                 # first observations are damped: no strong beliefs yet
HISTORY = 60


def fmt_quantity(value: float, unit: str) -> str:
    if unit == "s":
        value = max(0.0, value)
        if value < 90:
            return f"{value:.0f}s"
        if value < 5400:
            return f"{value / 60:.0f}m"
        return f"{value / 3600:.1f}h"
    if unit == "tok":
        return f"{value / 1000:.1f}k" if value >= 1000 else f"{value:.0f}"
    return f"{value:.2f}"


@dataclass
class Observation:
    key: str
    raw: float
    expected: float          # in raw units (or a probability for bern)
    surprise: float
    direction: int           # +1 above expectation, -1 below, 0 none

    def describe(self) -> str:
        spec = FEATURES.get(self.key)
        if not spec:
            return f"{self.key} was unexpected"
        text = spec.more if self.direction > 0 else spec.less
        if spec.kind == "gauss" and spec.unit:
            text += f" ({fmt_quantity(self.raw, spec.unit)}; you expected ~{fmt_quantity(self.expected, spec.unit)})"
        return text


@dataclass
class Feature:
    key: str
    kind: str
    mean: float = 0.0
    var: float = 0.5
    n: int = 0
    base_alpha: float = 0.2
    last: Optional[dict] = None
    history: Deque[dict] = field(default_factory=lambda: deque(maxlen=HISTORY))

    MIN_VAR = 0.04

    def _x(self, raw: float) -> float:
        if self.kind == "gauss":
            return math.log1p(max(0.0, raw))
        return 1.0 if raw else 0.0

    def expected_raw(self) -> float:
        if self.kind == "gauss":
            return math.expm1(self.mean)
        return self.mean

    def observe(self, raw: float, now: Optional[float] = None) -> Observation:
        x = self._x(raw)
        now = now or time.time()

        if self.n == 0:
            self.mean = x if self.kind == "gauss" else (0.6 if x else 0.2)
            self.n = 1
            obs = Observation(self.key, raw, self.expected_raw(), 0.0, 0)
            self._record(now, raw, obs)
            return obs

        expected = self.expected_raw()
        err = x - self.mean
        if self.kind == "gauss":
            z2 = err * err / (self.var + 1e-9)
            surprise = 1.0 - math.exp(-z2 / 8.0)
        else:
            p = min(0.98, max(0.02, self.mean))
            info = -math.log2(p if x else 1.0 - p)
            surprise = 1.0 - math.exp(-max(0.0, info - 0.5) / 2.5)
        if self.n < WARMUP:
            surprise *= self.n / WARMUP

        # Surprise is the learning signal: bigger error, faster belief update.
        alpha = min(0.5, self.base_alpha * (1.0 + surprise))
        if self.kind == "gauss":
            self.mean += alpha * err
            self.var = max(self.MIN_VAR, (1 - alpha) * (self.var + alpha * err * err))
        else:
            self.mean = min(0.98, max(0.02, self.mean + alpha * err))
        self.n += 1

        direction = 0 if abs(err) < 1e-9 else (1 if err > 0 else -1)
        obs = Observation(self.key, raw, expected, surprise, direction)
        self._record(now, raw, obs)
        return obs

    def _record(self, now: float, raw: float, obs: Observation):
        self.last = {
            "t": now, "raw": raw, "expected": obs.expected,
            "surprise": round(obs.surprise, 4), "direction": obs.direction,
        }
        self.history.append({"t": now, "raw": raw, "expected": obs.expected, "surprise": round(obs.surprise, 4)})

    def to_dict(self) -> dict:
        return {
            "key": self.key, "kind": self.kind, "mean": self.mean, "var": self.var,
            "n": self.n, "last": self.last, "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Feature":
        f = cls(d["key"], d["kind"], d.get("mean", 0.0), d.get("var", 0.5), d.get("n", 0))
        f.last = d.get("last")
        f.history.extend(d.get("history", []))
        return f


class Predictor:
    """Holds one belief per channel feature."""

    def __init__(self):
        self.features: Dict[str, Feature] = {}

    def observe(self, key: str, raw: float, now: Optional[float] = None) -> Observation:
        if key not in self.features:
            spec = FEATURES.get(key)
            self.features[key] = Feature(key, spec.kind if spec else "gauss")
        return self.features[key].observe(raw, now)

    def snapshot(self) -> List[dict]:
        out = []
        for key, f in self.features.items():
            spec = FEATURES.get(key)
            d = f.to_dict()
            d["expected"] = f.expected_raw()
            d["std_factor"] = math.exp(math.sqrt(f.var)) if f.kind == "gauss" else None
            d["source"] = spec.source if spec else ""
            d["unit"] = spec.unit if spec else ""
            out.append(d)
        return out

    def to_dict(self) -> dict:
        return {k: f.to_dict() for k, f in self.features.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "Predictor":
        p = cls()
        for k, fd in (d or {}).items():
            p.features[k] = Feature.from_dict(fd)
        return p


# ── Agent-authored expectations ──────────────────────────────────

EXPECTATION_CHANNELS = {
    "door": "a message or task arrives at the door",
    "bench": "the bench changes",
}


@dataclass
class Expectation:
    text: str
    channel: str
    deadline: float
    created: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: str = "pending"          # pending | met | violated
    resolved_at: Optional[float] = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "Expectation":
        return cls(**{k: d[k] for k in ("text", "channel", "deadline", "created", "id", "status", "resolved_at") if k in d})
