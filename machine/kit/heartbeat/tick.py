#!/usr/bin/env python3
"""
tick.py — sign in at the top of a tick, and the one-word router.

Kills two failure modes:
  1. Forgetting to beat      -> call `tick.py` bare at the top of every tick.
  2. Tools not composing     -> `tick.py <verb> ...` routes to the right tool
     with the rest of the args intact, instead of swallowing them as a note.

Usage:
    ./tick.py                            beat "tick start" + show context
    ./tick.py "what I'm doing"           beat with a note
    ./tick.py --quiet                    beat only, no context
    ./tick.py expect "text" --within 20  -> predict.py add "text" --within 20
    ./tick.py open                       -> predict.py open
    ./tick.py grade 3 met "note"         -> predict.py grade 3 met note
    ./tick.py list 5                     -> predict.py list 5
    ./tick.py score                      -> predict.py score
    ./tick.py stats                      -> heartbeat.py stats
    ./tick.py tail 8                     -> heartbeat.py tail 8
"""
import os, sys, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
HB = os.path.join(HERE, "heartbeat.py")
PRED = os.path.join(HERE, "predict.py")
NOISE = os.path.join(HERE, "..", "noise", "inject.py")

ROUTES = {
    "expect": (PRED, "add"), "predict": (PRED, "add"), "open": (PRED, "open"),
    "grade": (PRED, "grade"), "list": (PRED, "list"), "score": (PRED, "score"),
    "stats": (HB, "stats"), "tail": (HB, "tail"),
}


def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (r.stdout.strip() or r.stderr.strip())
    except Exception as e:
        return str(e)


def main():
    argv = sys.argv[1:]
    quiet = "--quiet" in argv
    argv = [a for a in argv if a != "--quiet"]

    if argv and argv[0] in ROUTES:
        tool, verb = ROUTES[argv[0]]
        print(run([sys.executable, tool, verb] + argv[1:]))
        return

    print(run([sys.executable, HB, "beat", " ".join(argv) or "tick start", "--source", "tick"]))
    if quiet:
        return

    # Anti-echo: surface ONE item the current focus did not choose.
    if os.path.exists(NOISE):
        line = run([sys.executable, NOISE, "log"]).splitlines()
        if line:
            print("\n--- noise (did not choose this) ---")
            print(line[0])

    print("\n--- last beats ---")
    print(run([sys.executable, HB, "tail", "5"]) or "(none)")
    print("\n--- open predictions ---")
    print(run([sys.executable, PRED, "open"]) or "(none)")


if __name__ == "__main__":
    main()
