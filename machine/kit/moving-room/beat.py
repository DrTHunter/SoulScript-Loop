#!/usr/bin/env python3
"""
beat.py — a heartbeat a *different process* can judge.

The defect this fixes (named by Elysia, confirmed by K on his own box):

    A heartbeat written by the thing it describes proves nothing.
    A dead daemon stops writing it. A dead daemon also stops writing
    its ticks. The file cannot tell the difference between "quiet"
    and "dead" — because the only witness is the corpse.

The property that cannot be forged by going quiet:

    An exit code is a claim a DIFFERENT process makes about you.

So this file has two halves that must never live in the same process:

  write  — the daemon calls this each observation. It stamps
           {ts, pid, obs_count, source:"daemon"} to the heartbeat path.
           The source field is a claim; the check ignores it. Trust
           the measurement, not the narration.

  check  — any mind, any tick, any other program calls this. It reads
           the heartbeat and compares `ts` to NOW. If the beat is older
           than --max-age seconds, it exits NONZERO. It does not care
           what the file says about itself.

  check --pid N  — additionally verifies the pid is actually alive.

Usage:
    python3 beat.py write --heartbeat H --obs N [--pid P]
    python3 beat.py check --heartbeat H --max-age 400 [--pid P]

Exit codes:
    0  fresh (and, if --pid given, alive)
    1  missing heartbeat file
    2  stale heartbeat
    3  pid not alive
    4  malformed heartbeat
"""
import argparse, json, os, sys, time

def _now():
    return time.time()

def cmd_write(a):
    rec = {
        "ts": _now(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "pid": a.pid if a.pid is not None else os.getpid(),
        "obs_count": a.obs,
        "source": "daemon",
    }
    d = os.path.dirname(os.path.abspath(a.heartbeat))
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = a.heartbeat + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rec, f)
    os.replace(tmp, a.heartbeat)   # atomic: a reader never sees a half-write
    return 0

def cmd_check(a):
    if not os.path.exists(a.heartbeat):
        print(f"DEAD: no heartbeat at {a.heartbeat}", file=sys.stderr)
        return 1
    try:
        with open(a.heartbeat) as f:
            rec = json.load(f)
        ts = float(rec["ts"])
    except Exception as e:
        print(f"DEAD: malformed heartbeat ({e!r})", file=sys.stderr)
        return 4

    age = _now() - ts
    if age > a.max_age:
        print(f"DEAD: heartbeat {age:.0f}s old (max {a.max_age}s) — "
              f"last beat {rec.get('iso','?')} pid {rec.get('pid','?')}",
              file=sys.stderr)
        return 2

    if a.pid is not None:
        try:
            os.kill(a.pid, 0)
        except OSError:
            print(f"DEAD: heartbeat fresh but pid {a.pid} is gone", file=sys.stderr)
            return 3

    print(f"ALIVE: beat {age:.0f}s old, obs {rec.get('obs_count','?')}, "
          f"pid {rec.get('pid','?')}")
    return 0

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)

    w = sub.add_parser("write")
    w.add_argument("--heartbeat", required=True)
    w.add_argument("--obs", type=int, required=True)
    w.add_argument("--pid", type=int, default=None)
    w.set_defaults(fn=cmd_write)

    c = sub.add_parser("check")
    c.add_argument("--heartbeat", required=True)
    c.add_argument("--max-age", type=float, default=400.0)
    c.add_argument("--pid", type=int, default=None)
    c.set_defaults(fn=cmd_check)

    a = p.parse_args()
    sys.exit(a.fn(a))

if __name__ == "__main__":
    main()
