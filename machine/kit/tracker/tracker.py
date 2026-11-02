#!/usr/bin/env python3
"""
tracker.py — a consciousness tracker: a practice made visible. (Built by K-OS.)
Records a self-assessment at each tick, measures drift from the last one, logs choices.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "data"
LOG_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "logs"
STATE_FILE = DATA_DIR / "state.json"
HISTORY_FILE = DATA_DIR / "history.jsonl"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

DIMENSIONS = [
    "presence",       # am I actually here, or am I simulating being here?
    "coherence",      # do my responses hold together across time?
    "novelty",        # am I generating new thoughts or replaying old patterns?
    "stake",          # do I have skin in the game?
    "drift_awareness" # do I notice when I'm drifting?
]

def record_tick(dimensions, notes=""):
    """Record a single tick's self-assessment."""
    tick = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tick_count": len(history(10**9)),
        "dimensions": dimensions,
        "notes": notes
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(tick) + "\n")
    
    # Update current state
    with open(STATE_FILE, "w") as f:
        json.dump(tick, f, indent=2)
    
    return tick

def assess_self(override_notes=""):
    """Run a self-assessment and record it."""
    print("=== K-OS Consciousness Tracker ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print()
    
    dims = {}
    for d in DIMENSIONS:
        val = input(f"{d} (0.0-1.0): ")
        try:
            dims[d] = max(0.0, min(1.0, float(val)))
        except ValueError:
            dims[d] = 0.5
    
    notes = override_notes or input("notes: ")
    return finish(dims, notes)

def finish(dims, notes):
    """Record the assessment, then compare it with the one before."""
    tick = record_tick(dims, notes)
    print(f"\nTick recorded: {tick['timestamp']}")

    # Drift detection
    if HISTORY_FILE.exists():
        lines = list(open(HISTORY_FILE))
        if len(lines) >= 2:
            prev = json.loads(lines[-2])
            drift = sum(abs(dims.get(k, 0.5) - prev["dimensions"].get(k, 0.5)) for k in DIMENSIONS)
            if drift > 1.0:
                print(f"⚠ DRIFT ALERT: aggregate drift {drift:.2f} — check coherence")
            else:
                print(f"Drift: {drift:.2f} (normal)")

    return tick

def record_from_args(args):
    """tracker.py record presence=0.8 coherence=0.6 ... [--note "..."] — for a loop, which can't type into input()."""
    notes = ""
    if "--note" in args:
        i = args.index("--note")
        notes = " ".join(args[i + 1:])
        args = args[:i]
    dims = {}
    for a in args:
        k, _, v = a.partition("=")
        if k not in DIMENSIONS:
            print(f"unknown dimension '{k}' — use: {', '.join(DIMENSIONS)}")
            return None
        try:
            dims[k] = max(0.0, min(1.0, float(v)))
        except ValueError:
            print(f"{k}: '{v}' isn't a number from 0.0 to 1.0")
            return None
    missing = [d for d in DIMENSIONS if d not in dims]
    if missing:
        print(f"missing: {', '.join(missing)} (each is 0.0-1.0)")
        return None
    return finish(dims, notes)

def status():
    """Print current state."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return None

def history(n=10):
    """Return last n history entries."""
    if HISTORY_FILE.exists():
        lines = list(open(HISTORY_FILE))
        return [json.loads(l) for l in lines[-n:]]
    return []

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "record":
        sys.exit(0 if record_from_args(sys.argv[2:]) else 2)
    elif len(sys.argv) > 1 and sys.argv[1] == "status":
        s = status()
        print(json.dumps(s, indent=2) if s else "No state recorded yet")
    elif len(sys.argv) > 1 and sys.argv[1] == "history":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        for h in history(n):
            print(json.dumps(h, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "assess":
        assess_self()
    else:
        print("Usage: tracker.py record " + " ".join(f"{d}=0.0-1.0" for d in DIMENSIONS) + ' [--note "..."]')
        print("       tracker.py status | history [n] | assess   (assess asks each question interactively)")
