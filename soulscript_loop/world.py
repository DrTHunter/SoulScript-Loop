"""The inner field: what the agent sees, arranged around what it is looking at.

There are no fixed places. Focus is whatever the agent attends to — a
message, a file, a memory, a search result, a topic it is turning over.
Everything else is laid out by how related it is to that focus:

    FOCUS   the thing itself, in full
    CLOSE   the most related things, clear
    AROUND  related enough to notice, as a gist
    EDGE    everything else, as faint traces

Change focus and the field rearranges. Standing senses (time, energy,
the feel of the last action) are HUD gauges, always visible. Surprise
flashes as an alert and strong new arrivals pull focus to themselves.
Unattended things fade; capacity is finite; mood is read off the field.
"""

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from .embedding import Embedder, cosine
from .prediction import FEATURES, SURPRISE_FLOOR, Expectation, Observation, Predictor

log = logging.getLogger(__name__)

GAUGE_KINDS = {"time", "energy", "body"}      # HUD readouts, not in the field
ALERT_KINDS = {"surprise", "alert"}           # flashes at the rim

SOURCES = {"door": "the door", "time": "time", "body": "your body", "bench": "your bench", "self": "your own mind"}


def source_name(source: str) -> str:
    return SOURCES.get(source, source)


FOCUS, CLOSE, AROUND, EDGE = 0, 1, 2, 3
RING_NAMES = ("focus", "close", "around", "edge")
CLOSE_N, AROUND_N = 4, 6
MIN_CLOSE_SIM = 0.12
CLOSE_RELATIVE = 0.45

FULL, GIST, TRACE = 0, 1, 2
DETAIL_NAMES = ("full", "gist", "trace")
RING_DETAIL = {FOCUS: FULL, CLOSE: FULL, AROUND: GIST, EDGE: TRACE}

# Seconds for salience to halve. Focus and holding slow it down.
HALF_LIFE = {
    "message": 6 * 3600, "task": 12 * 3600,
    "time": 600, "energy": 3600, "body": 1800,
    "intention": 6 * 3600, "expectation": 12 * 3600, "note": 2 * 3600,
    "work": 3 * 3600, "plan": 6 * 3600, "seen": 3600,
    "surprise": 900, "alert": 1800, "met": 900,
}

TRACES = {
    "message": "someone is waiting at the door", "task": "a task waits at the door",
    "work": "something on your bench", "plan": "a plan you made", "seen": "something you looked at",
    "intention": "something you meant to do", "expectation": "something you expect",
    "note": "a thought", "surprise": "something shifted", "alert": "a feeling", "met": "a settled expectation",
}

MAX_HELD = 3
FADE_FLOOR = 0.03


def _clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def local_dt(ts: float, tz_name: str = "UTC") -> datetime:
    """Wall time in your time zone; UTC if the name is unknown."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(ts, ZoneInfo(tz_name or "UTC"))
    except Exception:
        return datetime.fromtimestamp(ts, timezone.utc)


def fmt_age(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    if seconds < 172800:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds // 86400}d"


@dataclass
class Item:
    id: str
    key: str
    kind: str
    source: str
    text: str
    gist: str
    salience: float = 0.5
    valence: float = 0.0          # < 0 tension, > 0 harmony
    born: float = 0.0
    touched: float = 0.0
    fidelity: int = FULL
    held: bool = False
    resolved: bool = False
    anchor: bool = False          # a standing sense: compresses but never fades out
    grows: float = 0.0            # tension gained per hour while unresolved
    meta: dict = field(default_factory=dict)

    def trace(self, now: float) -> str:
        if self.anchor:
            return self.meta.get("trace") or self.gist
        base = TRACES.get(self.kind, f"something from {source_name(self.source)}")
        if self.kind == "message":
            return "an answered message" if self.resolved else f"{base} ({fmt_age(now - self.born)})"
        return base

    def line(self, level: int, now: float) -> str:
        if level <= FULL:
            return self.text
        if level == GIST:
            return self.gist
        return self.trace(now)

    def cost(self, now: float) -> int:
        return len(self.line(self.fidelity, now)) + 8

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        return cls(**d)


class InnerWorld:
    def __init__(self, capacity_chars: int = 2400, capture_threshold: float = 0.45,
                 embedder: Optional[Embedder] = None):
        self.capacity = capacity_chars
        self.capture_threshold = capture_threshold
        self.embedder = embedder
        self.tz = "UTC"   # set by the daemon: the clock her field is written in
        self.items: Dict[str, Item] = {}
        self.keys: Dict[str, str] = {}
        self.vectors: Dict[str, List[float]] = {}
        self.rings: Dict[str, Tuple[int, float]] = {}
        self.focus_item: Optional[str] = None
        self.focus_text = ""
        self.focus_vec: Optional[List[float]] = None
        self.deliberate = False
        self.dwell = 0
        self.predictor = Predictor()
        self.expectations: List[Expectation] = []
        self.valence = 0.0
        self.arousal = 0.0
        self.mood: dict = {}
        self.tick = 0
        self.seq = 0
        self.last_update: Optional[float] = None
        self.fade_log: List[dict] = []
        self._begin_tick()

    def _begin_tick(self):
        self.surprises: List[dict] = []
        self.faded: List[str] = []
        self.pulled: Optional[dict] = None
        self.arrivals: List[str] = []

    # ── Items ─────────────────────────────────────────────────────

    def get(self, ref: str) -> Optional[Item]:
        if ref in self.items:
            return self.items[ref]
        if ref in self.keys:
            return self.items.get(self.keys[ref])
        return None

    def gauge(self, key: str) -> Optional[Item]:
        it = self.get(key)
        return it if it and it.kind in GAUGE_KINDS else None

    def in_field(self) -> List[Item]:
        return [i for i in self.items.values() if i.kind not in GAUGE_KINDS | ALERT_KINDS]

    def alerts(self) -> List[Item]:
        return sorted((i for i in self.items.values() if i.kind in ALERT_KINDS), key=lambda i: -i.salience)

    def upsert(
        self, key: str, kind: str, source: str, text: str, gist: str = "",
        salience: float = 0.5, valence: float = 0.0, mode: str = "event",
        anchor: bool = False, grows: float = 0.0, meta: Optional[dict] = None,
        now: Optional[float] = None,
    ) -> Tuple[Item, bool]:
        """Bring something into the field, or refresh it.

        mode="event": a happening. New → arrives with its salience; repeated → only refreshes text.
        mode="level": a standing reading (energy, time). Salience and valence track the latest value.
        """
        now = now or time.time()
        gist = gist or _clip(text, 64)
        if key in self.keys and self.keys[key] in self.items:
            it = self.items[self.keys[key]]
            changed = it.text != text
            it.text, it.gist = text, gist
            if meta:
                it.meta.update(meta)
            if mode == "level":
                it.salience, it.valence = salience, valence
            elif changed:
                it.salience = max(it.salience, salience)
            if changed:
                it.touched = now
                it.fidelity = FULL
                self.vectors.pop(it.id, None)
            return it, False

        self.seq += 1
        it = Item(
            id=f"{(source or 'x')[0]}{self.seq}", key=key, kind=kind, source=source,
            text=text, gist=gist, salience=salience, valence=valence,
            born=now, touched=now, anchor=anchor, grows=grows, meta=dict(meta or {}),
        )
        self.items[it.id] = it
        self.keys[key] = it.id
        if mode == "event":
            self.arrivals.append(it.id)
        return it, True

    def drop(self, item: Item, reason: str = "faded"):
        self.items.pop(item.id, None)
        if self.keys.get(item.key) == item.id:
            del self.keys[item.key]
        vec = self.vectors.pop(item.id, None)
        self.rings.pop(item.id, None)
        if self.focus_item == item.id:
            # Losing the thing you were looking at leaves you holding its memory.
            self.focus_item, self.focus_text, self.focus_vec = None, item.gist, vec
        if reason == "faded" and item.kind not in ("surprise", "met"):
            self.faded.append(item.gist)
            self.fade_log.append({"t": time.time(), "tick": self.tick, "source": item.source,
                                  "kind": item.kind, "gist": item.gist})
            self.fade_log = self.fade_log[-50:]

    def resolve(self, item: Item, now: Optional[float] = None):
        if item.resolved:
            return
        item.resolved = True
        item.held = False
        item.grows = 0.0
        item.touched = now or time.time()
        item.valence = 0.3 if item.valence < 0 else max(item.valence, 0.2)

    def hold(self, item: Item) -> bool:
        if item.held:
            return True
        if sum(1 for i in self.items.values() if i.held) >= MAX_HELD:
            return False
        item.held = True
        item.fidelity = FULL
        return True

    def see(self, tool: str, args: dict, result: str, now: Optional[float] = None) -> Item:
        """Whatever you look at enters the field — and becomes your focus."""
        summary = ", ".join(f"{k}={_clip(str(v), 40)}" for k, v in sorted((args or {}).items()) if k != "content")
        key = f"seen:{tool}:{_clip(summary, 120)}"
        it, _ = self.upsert(key, "seen", tool, f"{tool}({summary}) → {_clip(result, 500)}",
                            gist=f"{tool}: {_clip(result, 48)}", salience=0.65, valence=0.05, now=now)
        self.move(item_id=it.id, deliberate=True)
        return it

    # ── Relatedness ───────────────────────────────────────────────

    def needs_vectors(self) -> List[Tuple[str, str]]:
        need = [(i.id, i.text) for i in self.in_field() if i.id not in self.vectors]
        if self.focus_text and not self.focus_item and self.focus_vec is None:
            need.append(("__focus__", self.focus_text))
        return need

    def set_vectors(self, pairs: Iterable[Tuple[str, List[float]]]):
        for key, vec in pairs:
            if key == "__focus__":
                self.focus_vec = vec
            elif key in self.items:
                self.vectors[key] = vec

    def ensure_vectors(self):
        need = self.needs_vectors()
        if not need or not self.embedder:
            return
        try:
            vecs = self.embedder([t for _, t in need])
        except Exception as exc:
            log.warning("[loop] embedding failed: %s", exc)
            return
        self.set_vectors(zip([k for k, _ in need], vecs))

    def _focus_vector(self) -> Optional[List[float]]:
        if self.focus_item and self.focus_item in self.items:
            return self.vectors.get(self.focus_item)
        return self.focus_vec

    def layout(self):
        """Arrange the field around the focus: most related closest."""
        fv = self._focus_vector()
        self.rings = {}
        if self.focus_item in self.items:
            self.rings[self.focus_item] = (FOCUS, 1.0)
        scored = [(i, cosine(self.vectors.get(i.id), fv) if fv else 0.0)
                  for i in self.in_field() if i.id != self.focus_item]
        held = [(i, s) for i, s in scored if i.held]
        loose = [(i, s) for i, s in scored if not i.held]
        loose.sort(key=(lambda p: (p[1], p[0].salience)) if fv else (lambda p: p[0].salience), reverse=True)
        for i, s in held:
            self.rings[i.id] = (CLOSE, s)
        slots = max(0, CLOSE_N - len(held))
        # "Close" is relative: embedders give unrelated text a baseline similarity.
        floor = getattr(self.embedder, "close_floor", MIN_CLOSE_SIM)
        bar = max(floor, (loose[0][1] if loose else 0.0) * CLOSE_RELATIVE)
        for n, (i, s) in enumerate(loose):
            if n < slots and (fv is None or s >= bar):
                ring = CLOSE
            elif n < slots + AROUND_N:
                ring = AROUND
            else:
                ring = EDGE
            self.rings[i.id] = (ring, s)

    def ring(self, item: Item) -> int:
        if item.kind in GAUGE_KINDS | ALERT_KINDS:
            return CLOSE
        return self.rings.get(item.id, (EDGE, 0.0))[0]

    def detail(self, item: Item) -> int:
        return max(item.fidelity, RING_DETAIL[self.ring(item)])

    def focus_label(self) -> str:
        it = self.items.get(self.focus_item) if self.focus_item else None
        if it:
            return it.gist
        if self.focus_text:
            return f'"{_clip(self.focus_text, 48)}"'
        return "nothing in particular"

    # ── Tick pipeline ─────────────────────────────────────────────

    def begin(self, tick: int):
        self.tick = tick
        self._begin_tick()

    def decay(self, now: float):
        """Time passes for everything, looked at or not."""
        if self.last_update is None:
            self.last_update = now
            return
        dt = max(0.0, now - self.last_update)
        self.last_update = now
        for it in list(self.items.values()):
            if it.grows and not it.resolved:
                g = it.grows * dt / 3600
                it.valence = max(-1.0, it.valence - g)
                it.salience = min(1.0, it.salience + g * 0.5)
            if it.anchor:
                continue
            hl = HALF_LIFE.get(it.kind, 3600)
            if self.ring(it) <= CLOSE and it.kind not in ALERT_KINDS:
                hl *= 2
            if it.held:
                hl *= 4
            if it.resolved:
                hl /= 3
            it.salience *= 0.5 ** (dt / hl)
            if it.salience < FADE_FLOOR and not it.held and it.id != self.focus_item:
                self.drop(it)

    def perceive(self, key: str, raw: float, now: float) -> Observation:
        """Bottom-up: compare an observation to the standing prediction."""
        obs = self.predictor.observe(key, raw, now)
        if obs.surprise >= SURPRISE_FLOOR and obs.direction:
            spec = FEATURES.get(key)
            source = spec.source if spec else "body"
            text = obs.describe()
            if text:
                self.surprises.append({"key": key, "source": source, "surprise": round(obs.surprise, 3), "text": text})
                self.upsert(f"surprise:{key}", "surprise", source, text, gist=_clip(text, 48),
                            salience=min(1.0, 0.3 + obs.surprise), valence=-0.35 * obs.surprise,
                            now=now, meta={"surprise": obs.surprise})
                for it in self.items.values():
                    if it.source == source and it.kind not in ALERT_KINDS:
                        it.salience = min(1.0, it.salience + 0.3 * obs.surprise)
        return obs

    def check_expectations(self, events: Iterable[str], now: float):
        """Top-down: test the agent's own predictions against what happened."""
        events = set(events)
        for ex in self.expectations:
            if ex.status != "pending":
                continue
            item = self.get(f"expect:{ex.id}")
            if ex.channel in events:
                ex.status, ex.resolved_at = "met", now
                self.upsert(f"met:{ex.id}", "met", "self", f"as you expected: {ex.text}",
                            salience=0.45, valence=0.45, now=now)
                if item:
                    self.drop(item, reason="settled")
            elif now >= ex.deadline:
                ex.status, ex.resolved_at = "violated", now
                text = f"you expected {ex.text} — it didn't happen"
                self.surprises.append({"key": f"expect.{ex.channel}", "source": ex.channel, "surprise": 0.7, "text": text})
                self.upsert(f"broken:{ex.id}", "surprise", ex.channel, text, salience=0.8, valence=-0.4, now=now)
                if item:
                    self.drop(item, reason="settled")
        self.expectations = [e for e in self.expectations if e.status == "pending"] + \
            [e for e in self.expectations if e.status != "pending"][-20:]

    def expect(self, text: str, channel: str, within_minutes: float, now: Optional[float] = None) -> Expectation:
        now = now or time.time()
        ex = Expectation(text=text, channel=channel, deadline=now + within_minutes * 60, created=now)
        self.expectations.append(ex)
        when = local_dt(ex.deadline, self.tz).strftime("%H:%M %Z")
        self.upsert(f"expect:{ex.id}", "expectation", "self",
                    f"you expect {text} from {source_name(channel)} by {when}",
                    gist=f"expect: {_clip(text, 40)}", salience=0.55, valence=0.0,
                    mode="level", now=now, meta={"expectation": ex.id})
        return ex

    def move(self, item_id: Optional[str] = None, text: Optional[str] = None, deliberate: bool = True):
        """Shift focus to an item, to a topic (free text), or to nothing (let the gaze wander)."""
        text = "" if item_id else (text or "").strip()
        if item_id != self.focus_item or text != self.focus_text:
            self.dwell = 0
        self.focus_item, self.focus_text, self.focus_vec = item_id, text, None
        self.deliberate = deliberate
        if item_id and item_id in self.items:
            self.items[item_id].fidelity = FULL   # looking at a thing brings it back into detail

    def capture(self):
        """Involuntary attention: a strong enough new arrival pulls focus to itself."""
        threshold = self.capture_threshold + (0.2 if self.deliberate else 0.0)
        best: Optional[Item] = None
        for iid in self.arrivals:
            it = self.items.get(iid)
            if not it or it.kind in GAUGE_KINDS | ALERT_KINDS or it.resolved or iid == self.focus_item:
                continue
            if it.salience >= threshold and (best is None or it.salience > best.salience):
                best = it
        if best:
            self.pulled = {"from": self.focus_label(), "to": best.id, "by": best.gist}
            self.move(item_id=best.id, deliberate=False)
        else:
            self.dwell += 1

    def used(self, now: float) -> int:
        return sum(i.cost(now) for i in self.items.values())

    def fit(self, now: float):
        """Hold the field to its capacity: compress the least salient, least related, then let go."""
        prox = {FOCUS: 1.5, CLOSE: 1.0, AROUND: 0.75, EDGE: 0.5}
        used = self.used(now)
        guard = 0
        while used > self.capacity and guard < 500:
            guard += 1
            candidates = [i for i in self.items.values()
                          if i.id != self.focus_item and not (i.anchor and i.fidelity >= TRACE)]
            if not candidates:
                break
            loose = [i for i in candidates if not i.held] or candidates

            def keep_score(i: Item) -> float:
                weight = 1.3 if i.kind in ("message", "task") and not i.resolved else 1.0
                return i.salience * prox[self.ring(i)] * weight

            victim = min(loose, key=keep_score)
            before = victim.cost(now)
            if victim.fidelity < TRACE:
                victim.fidelity += 1
                used += victim.cost(now) - before
            else:
                self.drop(victim)
                used -= before

    def compute_mood(self, energy: float, now: float) -> dict:
        by_source: Dict[str, Dict[str, float]] = {}
        top_t: Tuple[float, Optional[Item]] = (0.0, None)
        top_h: Tuple[float, Optional[Item]] = (0.0, None)
        t_total = h_total = 0.0
        for it in self.items.values():
            src = by_source.setdefault(it.source, {"tension": 0.0, "harmony": 0.0})
            if it.valence < 0 and not it.resolved:
                t = it.salience * -it.valence
                t_total += t
                src["tension"] += t
                if t > top_t[0]:
                    top_t = (t, it)
            elif it.valence > 0:
                h = it.salience * it.valence
                h_total += h
                src["harmony"] += h
                if h > top_h[0]:
                    top_h = (h, it)
        self.valence = 0.75 * self.valence + 0.25 * math.tanh(h_total - t_total)
        tick_surprise = min(1.0, sum(s["surprise"] for s in self.surprises))
        self.arousal = 0.7 * self.arousal + 0.3 * tick_surprise
        clutter = self.used(now) / max(1, self.capacity)

        if energy < 0.15:
            word = "drained"
        elif self.valence >= 0.2:
            word = "bright" if self.arousal >= 0.35 else "settled"
        elif self.valence <= -0.2:
            word = "unsettled" if self.arousal >= 0.35 else "heavy"
        elif self.arousal >= 0.35:
            word = "alert"
        elif clutter > 0.85:
            word = "crowded"
        else:
            word = "quiet"

        parts = []
        if top_t[1] and top_t[0] > 0.15:
            parts.append(f'tension gathers around "{_clip(top_t[1].gist, 40)}"')
        if top_h[1] and top_h[0] > 0.15:
            parts.append(f'warmth around "{_clip(top_h[1].gist, 40)}"')
        if clutter > 0.85:
            parts.append("your field is crowded")
        if energy < 0.3:
            parts.append("you are running low")

        self.mood = {
            "word": word, "phrase": "; ".join(parts),
            "valence": round(self.valence, 3), "arousal": round(self.arousal, 3),
            "tension": round(t_total, 3), "harmony": round(h_total, 3),
            "clutter": round(clutter, 3), "energy": round(energy, 3),
            "by_source": {k: {kk: round(vv, 3) for kk, vv in v.items()} for k, v in by_source.items()},
        }
        return self.mood

    # ── Rendering: the HUD the agent sees through ─────────────────

    def _mark(self, it: Item) -> str:
        return "◆ " if it.held else ("✓ " if it.resolved else "")

    def render(self, now: float, header: dict) -> str:
        dt = local_dt(now, self.tz)
        lines = [f"FIELD · tick {self.tick} · {dt:%a %d %b %H:%M %Z}, {header.get('part_of_day', '')}".rstrip(", ")]

        hud = []
        t = self.gauge("time")
        if t:
            hud.append(f"⏱ {t.gist}")
        energy = header.get("energy")
        if energy is not None:
            bar = "▮" * round(energy * 10) + "▱" * (10 - round(energy * 10))
            hud.append(f"⚡ {bar} {energy * 100:.0f}%" + (f" ({header['tokens_left']} tokens left today)" if header.get("tokens_left") else ""))
        waiting = sum(1 for i in self.items.values() if i.kind in ("message", "task") and not i.resolved)
        hud.append(f"✉ {waiting} waiting")
        hud.append(f"field {min(999, self.used(now) * 100 // max(1, self.capacity))}% full")
        lines.append(" · ".join(hud))
        if header.get("clock"):
            lines.append(header["clock"])
        if header.get("pace"):
            lines.append(header["pace"])
        body = self.gauge("proprio")
        if body:
            lines.append(f"✋ {body.text}")
        if header.get("woke"):
            lines.append(header["woke"])
        if self.mood:
            lines.append(f"Mood: {self.mood['word']}" + (f" — {self.mood['phrase']}." if self.mood.get("phrase") else "."))
        if self.pulled:
            lines.append(f"Your focus was pulled from {self.pulled['from']} by: {self.pulled['by']}")

        focus = self.items.get(self.focus_item) if self.focus_item else None
        if focus:
            lines.append(f"\nFOCUS ▸ [{focus.id}] {self._mark(focus)}{focus.text}")
        elif self.focus_text:
            lines.append(f'\nFOCUS ▸ "{self.focus_text}" — a thought you are holding up to the light')
        else:
            lines.append("\nFOCUS ▸ nothing in particular — your gaze wanders; the most salient things sit closest")

        rings: Dict[int, List[Item]] = {CLOSE: [], AROUND: [], EDGE: []}
        for it in self.in_field():
            if it.id != self.focus_item:
                rings[self.ring(it)].append(it)
        for ring in (CLOSE, AROUND):
            if not rings[ring]:
                continue
            lines.append(RING_NAMES[ring].upper())
            for it in sorted(rings[ring], key=lambda i: -self.rings.get(i.id, (0, 0.0))[1] - i.salience * 0.01):
                lines.append(f"  [{it.id}] {self._mark(it)}{it.line(self.detail(it), now)}")
        if rings[EDGE]:
            edge = sorted(rings[EDGE], key=lambda i: -i.salience)
            traces = list(dict.fromkeys(i.trace(now) for i in edge))
            lines.append("EDGE")
            lines.append("  " + " · ".join(traces[:8]) + (f" · … {len(traces) - 8} more" if len(traces) > 8 else ""))

        alerts = self.alerts()
        if alerts:
            lines.append("ALERTS")
            for it in alerts[:5]:
                lines.append(f"  ! {it.line(min(it.fidelity, GIST), now)}")

        new_far = {self.items[i].source for i in self.arrivals
                   if i in self.items and self.ring(self.items[i]) == EDGE}
        if new_far:
            lines.append("Something new at the edge of your sight, from: " + ", ".join(source_name(s) for s in sorted(new_far)) + ".")
        if self.faded:
            lines.append("Slipped away: " + "; ".join(f'"{g}"' for g in self.faded[:5]) + ".")
        return "\n".join(lines)

    # ── Inspection / persistence ──────────────────────────────────

    def snapshot(self, now: Optional[float] = None) -> dict:
        now = now or time.time()
        items = []
        for it in self.items.values():
            d = it.to_dict()
            ring = self.ring(it)
            level = self.detail(it)
            group = "gauge" if it.kind in GAUGE_KINDS else "alert" if it.kind in ALERT_KINDS else RING_NAMES[ring]
            d.update(ring=group, sim=round(self.rings.get(it.id, (0, 0.0))[1], 3), detail=DETAIL_NAMES[level],
                     fidelity_name=DETAIL_NAMES[it.fidelity], shown=it.line(level, now), cost=it.cost(now),
                     source_name=source_name(it.source))
            items.append(d)
        return {
            "tick": self.tick,
            "focus": {"item": self.focus_item, "text": self.focus_text, "label": self.focus_label()},
            "deliberate": self.deliberate, "dwell": self.dwell,
            "items": sorted(items, key=lambda d: -d["salience"]),
            "capacity": self.capacity, "used": self.used(now),
            "mood": self.mood,
            "surprises": self.surprises, "faded": self.faded, "pulled": self.pulled,
            "fade_log": self.fade_log[-30:],
            "expectations": [e.to_dict() for e in self.expectations],
        }

    def to_dict(self) -> dict:
        return {
            "items": [i.to_dict() for i in self.items.values()],
            "focus_item": self.focus_item, "focus_text": self.focus_text, "deliberate": self.deliberate,
            "dwell": self.dwell, "predictor": self.predictor.to_dict(),
            "expectations": [e.to_dict() for e in self.expectations],
            "valence": self.valence, "arousal": self.arousal, "mood": self.mood,
            "tick": self.tick, "seq": self.seq, "last_update": self.last_update,
            "fade_log": self.fade_log,
        }

    @classmethod
    def from_dict(cls, d: dict, capacity_chars: int = 2400, capture_threshold: float = 0.45,
                  embedder: Optional[Embedder] = None) -> "InnerWorld":
        w = cls(capacity_chars, capture_threshold, embedder)
        for idata in d.get("items", []):
            if "source" not in idata:
                continue   # pre-field (room) state: start clean
            it = Item.from_dict(idata)
            w.items[it.id] = it
            w.keys[it.key] = it.id
        w.focus_item = d.get("focus_item") if d.get("focus_item") in w.items else None
        w.focus_text = d.get("focus_text", "")
        w.deliberate = d.get("deliberate", False)
        w.dwell = d.get("dwell", 0)
        w.predictor = Predictor.from_dict({k: v for k, v in d.get("predictor", {}).items() if k in FEATURES})
        w.expectations = [Expectation.from_dict(e) for e in d.get("expectations", [])]
        w.valence, w.arousal = d.get("valence", 0.0), d.get("arousal", 0.0)
        w.mood = d.get("mood", {})
        w.tick, w.seq = d.get("tick", 0), d.get("seq", 0)
        w.last_update = d.get("last_update")
        w.fade_log = d.get("fade_log", [])
        w.layout()
        return w
