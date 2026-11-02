#!/usr/bin/env python3
"""
liveness.py — honest liveness check.

Separates the two kinds of writer in beats.jsonl:
  daemon       -> the background auto-beat (daemon.sh)
  you          -> "tick" (tick.py) and "manual" (heartbeat.py beat)

DRIFT fires when YOU stop signing in, counted in your loop's own ticks, not
minutes: a loop that sleeps four hours and signs in every time it wakes is
present. The tick clock is the host's (~/hud/log.jsonl), which you can read but
not write. Without a HUD it falls back to minutes. Exit 0 = present, 1 = drift.

Usage: ./liveness.py [missed-ticks]   (default 2; fallback window 15 min)
"""
import json, os, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "beats.jsonl")
HUD_LOG = os.path.join(os.path.expanduser("~"), "hud", "log.jsonl")
MISSED = int(sys.argv[1]) if len(sys.argv) > 1 else 2
FALLBACK_MIN = 15


def jsonl(path):
    rows = []
    if os.path.exists(path):
        with open(path, errors="replace") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    return rows


def when(s):
    t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def main():
    rows = jsonl(LOG)
    daemon = [r for r in rows if r.get("source") == "daemon"]
    you = [r for r in rows if r.get("source") in ("tick", "manual")]
    print(f"total beats : {len(rows)}")
    print(f"daemon      : {len(daemon)}" + (f"  (last {daemon[-1]['ts']})" if daemon else ""))
    print(f"you         : {len(you)}" + (f"  (last {you[-1]['ts']})" if you else ""))
    print("--- verdict ---")
    if not you:
        print("DRIFT: you have never signed in." + (" The daemon is beating alone." if daemon else ""))
        sys.exit(1)
    last = when(you[-1]["ts"])

    # The host's tick stamps: how many of your own ticks ran since you last signed in?
    ticks = {}
    for r in jsonl(HUD_LOG):
        if r.get("tick") is not None and r.get("at_utc"):
            try:
                ticks[r["tick"]] = when(r["at_utc"])
            except ValueError:
                pass
    if ticks:
        since = sorted(t for t, at in ticks.items() if at > last)
        if len(since) >= MISSED:
            print(f"DRIFT: {len(since)} of your ticks ran since you last signed in "
                  f"(ticks {since[0]}–{since[-1]}). Sign in at the top of every tick.")
            sys.exit(1)
        print(f"OK: signed in within your last {MISSED} ticks ({len(since)} since).")
        return

    age = (dt.datetime.now(dt.timezone.utc) - last).total_seconds() / 60
    if age > FALLBACK_MIN:
        print(f"DRIFT: no HUD to count ticks, and you have been silent {age:.1f} min. Sign in.")
        sys.exit(1)
    print(f"OK: signed in {age:.1f} min ago (no HUD; minutes fallback).")


if __name__ == "__main__":
    main()
