"""Daily token budget — the agent's energy. It runs out, and that matters."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class DailyBudget:
    def __init__(self, path: Path, tokens_per_day: int, cost_per_day: float = 0.0):
        self.path = Path(path)
        self.tokens_per_day = max(1, int(tokens_per_day))
        self.cost_per_day = float(cost_per_day or 0.0)
        self.day = _today()
        self.tokens = 0
        self.cost = 0.0
        self.ticks = 0
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("day") == self.day:
                self.tokens = int(data.get("tokens", 0))
                self.cost = float(data.get("cost", 0.0))
                self.ticks = int(data.get("ticks", 0))
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.warning("[loop] budget file unreadable, starting fresh: %s", exc)

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"day": self.day, "tokens": self.tokens,
                                         "cost": round(self.cost, 6), "ticks": self.ticks}), encoding="utf-8")

    def _roll(self):
        today = _today()
        if today != self.day:
            self.day, self.tokens, self.cost, self.ticks = today, 0, 0.0, 0
            self._save()

    def spend(self, tokens: int, cost: float, tick: bool = True):
        self._roll()
        self.tokens += max(0, int(tokens))
        self.cost += max(0.0, float(cost))
        self.ticks += 1 if tick else 0
        self._save()

    @property
    def tokens_left(self) -> int:
        self._roll()
        return max(0, self.tokens_per_day - self.tokens)

    @property
    def energy(self) -> float:
        """Fraction of today's budget left, limited by whichever cap is tighter."""
        self._roll()
        frac = 1.0 - self.tokens / self.tokens_per_day
        if self.cost_per_day > 0:
            frac = min(frac, 1.0 - self.cost / self.cost_per_day)
        return max(0.0, min(1.0, frac))

    @property
    def exhausted(self) -> bool:
        return self.energy <= 0.0

    @staticmethod
    def seconds_until_reset() -> float:
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
        return (tomorrow - now).total_seconds()

    def to_dict(self) -> dict:
        self._roll()
        return {
            "day": self.day, "tokens": self.tokens, "tokens_per_day": self.tokens_per_day,
            "tokens_left": self.tokens_left, "cost": round(self.cost, 6),
            "cost_per_day": self.cost_per_day, "ticks": self.ticks,
            "energy": round(self.energy, 4), "resets_in": round(self.seconds_until_reset()),
        }
