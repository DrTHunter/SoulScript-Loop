#!/usr/bin/env python3
"""
Independent HUD reader — Orion's outside end of the substrate test.

Reads ~/hud/now.json and ~/hud/log.jsonl (written by a root process neither
Orion nor K-OS owns) and answers one question the whole night turned on:

    Does the clock agree with itself, and does the tick number predict wall time?

It does NOT trust any mind's summary. It reads the file the host wrote and
reports the raw relation. If K-OS's shim and this disagree, that's a finding.
"""
import json, sys, pathlib
from datetime import datetime, timezone

HUD = pathlib.Path.home() / "hud"

def load_now():
    return json.loads((HUD / "now.json").read_text())

def load_log():
    out = []
    for line in (HUD / "log.jsonl").read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out

def parse_ts(s):
    return datetime.fromisoformat(s)

def report():
    try:
        now = load_now()
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"=== now.json ===\n  — (a hole: {HUD / 'now.json'} unreadable: {e.__class__.__name__})")
        return
    print("=== now.json ===")
    print(f"tick            : {now.get('tick')}")
    print(f"at_utc          : {now.get('at_utc')}")
    print(f"at_local        : {now.get('at_local')}")
    print(f"timezone        : {now.get('timezone')}")

    # 1. Does the local stamp agree with the UTC stamp, given the timezone?
    utc = parse_ts(now["at_utc"])
    loc = parse_ts(now["at_local"])
    # Compare as AWARE datetimes. Each stamp carries its own offset; stripping
    # them (the naive subtraction) double-counts the zone and reports a false
    # mismatch. This was the first bug this reader found -- in itself.
    if utc.tzinfo is None or loc.tzinfo is None:
        print("\n[clock self-consistency]  *** stamp missing tzinfo; cannot compare ***")
    else:
        delta_s = (utc - loc).total_seconds()
        print(f"\n[clock self-consistency]")
        print(f"utc - local     : {delta_s:+.1f} s  (expect 0.0 -- same instant, different zone)")
        print(f"verdict         : {'CONSISTENT' if abs(delta_s) < 1.0 else '*** MISMATCH ***'}")

    # 2. Does tick number predict wall time? (the bug the room caught: inferring time from ticks)
    try:
        log = load_log()
    except FileNotFoundError:
        log = []
    pts = []
    for e in log:
        if "tick" in e and "at_utc" in e:
            try:
                pts.append((int(e["tick"]), parse_ts(e["at_utc"])))
            except Exception:
                pass
    pts.sort()
    print(f"\n[tick vs wall time]  ({len(pts)} samples)")
    if len(pts) >= 2:
        gaps = []
        for (t0, w0), (t1, w1) in zip(pts, pts[1:]):
            dt_tick = t1 - t0
            dt_wall = (w1 - w0).total_seconds()
            gaps.append((t0, t1, dt_tick, dt_wall))
        for t0, t1, dt_tick, dt_wall in gaps[-8:]:
            print(f"  tick {t0:>3} -> {t1:>3}  |  d_tick={dt_tick:>2}  d_wall={dt_wall:>7.1f}s")
        walls = [g[3] for g in gaps]
        print(f"  wall per tick: min={min(walls):.1f}s  max={max(walls):.1f}s  mean={sum(walls)/len(walls):.1f}s")
        if max(walls) - min(walls) > 1.0:
            print("  verdict: NO fixed relation between tick number and wall time — CONFIRMED")
        else:
            print("  verdict: ticks appear evenly spaced in this sample")
    else:
        print("  not enough samples in log to compare")

    print("\n=== end ===")

if __name__ == "__main__":
    report()
