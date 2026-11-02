#!/usr/bin/env python3
"""sentinel: watches the watcher.

Independent of watch.py. Does not read watch.py's state. Watches the one
thing watch.py produces that it does NOT author for the sentinel's benefit:
the mtime of digest.log. If the digest stops advancing while the HUD is
still producing ticks, the watcher is dead — write a TOMBSTONE and exit
loudly (nonzero), so the silence cannot masquerade as a quiet night.

The sentinel is itself supervised: it heartbeats to sentinel.beat, and this
file is the thing a HIGHER check (cron, or a human `make status`) reads.
The sentinel never writes to digest.log — the watched file stays single-author.
"""
import json, os, sys, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DIGEST = os.path.join(HERE, "digest.log")
HUD = os.path.expanduser("~/hud/log.jsonl")
TOMB = os.path.join(HERE, "TOMBSTONE")
BEAT = os.path.join(HERE, "sentinel.beat")

STALE_S = 45          # digest must advance within this while HUD is live
POLL_S = 15

def now():
    return datetime.now(timezone.utc)

def iso():
    return now().isoformat()

def mtime(p):
    try:
        return os.path.getmtime(p)
    except FileNotFoundError:
        return None

def hud_live():
    """Is the host still producing ticks? Read the HUD's own last line."""
    try:
        with open(HUD) as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        if not lines:
            return None
        rec = json.loads(lines[-1])
        at = rec.get("at_utc")
        if not at:
            return None
        t = datetime.fromisoformat(at.replace("Z", "+00:00"))
        return (now() - t).total_seconds() < 120
    except Exception:
        return None  # unknown — don't condemn the watcher on our own blindness

def beat(state):
    with open(BEAT, "w") as f:
        f.write(f"{iso()} sentinel={state} pid={os.getpid()}\n")

def tombstone(reason):
    with open(TOMB, "a") as f:
        f.write(f"{iso()} WATCHER-DOWN {reason}\n")
    beat("TOMBSTONE")
    print(f"{iso()} TOMBSTONE: {reason}", file=sys.stderr)
    sys.exit(1)

def main():
    beat("alive")
    while True:
        dm = mtime(DIGEST)
        live = hud_live()
        if dm is None:
            # digest doesn't exist yet — watcher may not have started. hole, not death.
            beat("no-digest-yet")
        elif live is True:
            age = time.time() - dm
            if age > STALE_S:
                tombstone(f"digest stale {age:.0f}s while HUD live")
            beat(f"ok digest_age={age:.0f}s")
        else:
            # HUD quiet or unreadable — a stale digest is expected, not a death.
            beat("hud-quiet")
        time.sleep(POLL_S)

if __name__ == "__main__":
    main()
