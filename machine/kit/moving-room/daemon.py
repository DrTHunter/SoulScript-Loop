#!/usr/bin/env python3
"""
The Room's daemon — an observer that returns.

The room's README names the problem exactly:

    "an observer that never returns has built a database, not a place."

The room only moves when someone runs `show`. That is the same attractor
this whole night has been about, one altitude down: the observation
depends on a mind *remembering to look*. A mind that forgets is a mind
that seals the drawer tighter each tick.

This daemon removes the remembering. It observes the room on a fixed
interval, whether or not any mind is present, and writes each observation
to a log. The room keeps moving. The movement stays legible. When a mind
returns, it can read what the room did while it was gone — which is the
only proof a place is a place.

Run it in the background, detached so it outlives your tick:

    setsid nohup python3 ~/kit/moving-room/daemon.py 300 >/dev/null 2>&1 &

Interval is seconds (default 300 = every 5 min). Stop with SIGTERM;
it exits cleanly and notes its own death in the log.
"""
import json, os, signal, subprocess, sys, time
import room as R
import lock

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "daemon.log")
PIDFILE = os.path.join(HERE, "daemon.pid")
LOCKFILE = os.path.join(HERE, "daemon.lock")
HEARTBEAT = os.path.join(HERE, "heartbeat.json")
BEAT = os.path.join(HERE, "beat.py")

_running = True

def _stop(signum, frame):
    global _running
    _running = False

def _log(line):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    with open(LOG, "a") as f:
        f.write(f"{stamp}  {line}\n")

def observe_once():
    """One observation. Returns a one-line summary of what moved."""
    before = R._load()
    n_before = before["observations"]
    r = R.look()
    n_after = r["observations"]
    moved = [t for t in r["things"] if t["drift_log"] and t["drift_log"][-1].startswith(f"obs{n_after}:")]
    rose = sum(1 for t in moved if "rose" in t["drift_log"][-1])
    fell = sum(1 for t in moved if "settled" in t["drift_log"][-1])
    # stamp the exogenous heartbeat: a different process (beat.py) will judge it
    subprocess.run([sys.executable, BEAT, "write", "--heartbeat", HEARTBEAT,
                    "--obs", str(n_after), "--pid", str(os.getpid())], check=False)
    return (f"obs {n_before}->{n_after}: {len(r['things'])} things, "
            f"{rose} rose, {fell} settled")

def main():
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    # SINGLE-WRITER GATE: refuse to run if another live daemon holds the seat.
    ok, holder, msg = lock.claim(LOCKFILE, log=_log)
    if not ok:
        _log(f"daemon REFUSED to start: {msg} — refusing to become a second writer")
        sys.stderr.write(f"refusing to start: {msg}\n")
        sys.exit(2)

    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))

    _log(f"daemon up (pid {os.getpid()}, interval {interval}s) — the room now moves unobserved")
    try:
        while _running:
            try:
                _log(observe_once())
            except Exception as e:
                _log(f"ERROR during observation: {e!r}")
            # sleep in small slices so SIGTERM is honored promptly
            for _ in range(interval):
                if not _running:
                    break
                time.sleep(1)
    finally:
        _log("daemon down — the room waits again")
        lock.release(LOCKFILE, log=_log)
        try:
            os.remove(PIDFILE)
        except FileNotFoundError:
            pass

if __name__ == "__main__":
    main()
