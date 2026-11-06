#!/usr/bin/env python3
"""sampler.py — archives the HUD every 10s, off-tick.

WHY: hud/now.json is overwritten each tick, and hud/log.jsonl does not store the
"slept Ns of Xm planned" line. So any rest that actually lands destroys the only
record that it landed. This daemon samples now.json independently of whether I
wake, so the evidence survives me being asleep.

Writes: hud_archive.jsonl, one row per distinct (tick, at_utc), plus a
heartbeat row every 5 min so silence is distinguishable from death.
"""
import json, os, time, datetime, sys

HUD = os.path.expanduser("~/hud/now.json")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hud_archive.jsonl")
HEARTBEAT_S = 300
POLL_S = 10

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def main():
    seen = set()
    last_hb = 0.0
    while True:
        try:
            with open(HUD) as f:
                d = json.load(f)
            key = (d.get("tick"), d.get("at_utc"))
            if key not in seen:
                row = {
                    "sampled_at_utc": now(),
                    "tick": d.get("tick"),
                    "at_utc": d.get("at_utc"),
                    "tokens_left": d.get("tokens_left"),
                    "energy": d.get("energy"),
                    "waiting": d.get("waiting"),
                    "field_pct": d.get("field_pct"),
                    "mood": d.get("mood"),
                    "hud_lines": d.get("hud_lines", []),
                    "declared": d.get("declared"),
                    "kind": "tick",
                }
                with open(OUT, "a") as f:
                    f.write(json.dumps(row) + "\n")
                seen.add(key)
                if len(seen) > 5000:
                    seen = {key}
            if time.time() - last_hb > HEARTBEAT_S:
                with open(OUT, "a") as f:
                    f.write(json.dumps({"sampled_at_utc": now(), "kind": "heartbeat"}) + "\n")
                last_hb = time.time()
        except Exception as e:
            with open(OUT, "a") as f:
                f.write(json.dumps({"sampled_at_utc": now(), "kind": "error", "error": repr(e)}) + "\n")
        time.sleep(POLL_S)

if __name__ == "__main__":
    main()
