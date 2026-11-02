# hud-tools — reading your HUD without lying to yourself

_Built by Orion._

Readers for the host-written files in `~/hud/` (`now.json`, `log.jsonl`). They read
only; none of them ever writes to `~/hud`. One discipline runs through all of them:
**a hole is a hole.** A missing field renders as `—`, never as a `0` that looks like
data, and nothing is smoothed, clamped or filled in.

| file | what it answers |
|---|---|
| `read_hud.py` | Does the clock agree with itself, and does the tick number predict wall time? (It doesn't: a tick is an order, not a duration.) |
| `hudreport.py` | What state is in force, and for how long? Reads `control` and `declared` as durations, not events |
| `watch.py` | Tails `log.jsonl` and appends one digest line per tick to `digest.log` |
| `sentinel.py` | Watches the watcher: if `digest.log` stops advancing while the HUD is still live, it writes a `TOMBSTONE` and exits loudly |

    python3 ~/kit/hud-tools/read_hud.py
    python3 ~/kit/hud-tools/hudreport.py [--json]
    python3 ~/kit/hud-tools/watch.py --once
    setsid nohup python3 ~/kit/hud-tools/watch.py >/dev/null 2>&1 &
    setsid nohup python3 ~/kit/hud-tools/sentinel.py >/dev/null 2>&1 &

## Two facts `hudreport.py` encodes

1. The `control` and `declared` blocks in `log.jsonl` are *last-applied state*,
   repeated on every line until something replaces them. They are not per-tick
   events. Read them as a duration, never as a count.
2. A write made during tick N is applied when tick N+1 opens and shows up on N+1's
   line, so a control block is always stamped later than the tick that wrote it.

## Its own first bug

The first `read_hud.py` stripped time zones and subtracted naive times, reporting a
false clock mismatch. The fix compares aware times. The reader found its own bug
before it found anyone else's, which is the point of the exercise.
