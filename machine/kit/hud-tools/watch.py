#!/usr/bin/env python3
"""hud-watch: tails ~/hud/log.jsonl and appends a one-line digest per tick.

Read-only by construction: opens the HUD log for reading, writes only to
its own state file and digest. No `or 0`, no fallback — a missing field
renders as a missing stamp, never a zero that looks like data.
"""
import json, os, time, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
HUD = os.path.expanduser("~/hud/log.jsonl")
OUT = os.path.join(HERE, "digest.log")
STATE = os.path.join(HERE, ".offset")

def read_offset():
    try:
        with open(STATE) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0

def write_offset(n):
    with open(STATE, "w") as f:
        f.write(str(n))

def render(rec):
    # missing fields render as "—", never 0
    def g(k):
        v = rec.get(k)
        return "—" if v is None else v
    return (f"tick={g('tick')} at={g('at_utc')} energy={g('energy')} "
            f"waiting={g('waiting')} field={g('field_pct')} mood={g('mood')}")

def poll():
    n = 0
    with open(HUD, encoding="utf-8") as f:
        lines = f.readlines()
    off = read_offset()
    for line in lines[off:]:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            with open(OUT, "a", encoding="utf-8") as o:
                o.write(f"{datetime.now(timezone.utc).isoformat()} UNPARSEABLE —\n")
            n += 1
            continue
        with open(OUT, "a", encoding="utf-8") as o:
            o.write(f"{datetime.now(timezone.utc).isoformat()} {render(rec)}\n")
        n += 1
    write_offset(off + n)
    return n

if __name__ == "__main__":
    if "--once" in sys.argv:
        print(f"new lines: {poll()}")
        sys.exit(0)
    while True:
        try:
            poll()
        except FileNotFoundError:
            pass  # HUD not written yet; a hole, not a zero
        time.sleep(15)
