#!/usr/bin/env python3
"""hudreport -- read my own HUD without lying to myself.

Two facts this tool exists to encode, both learned the hard way:

1. ~/hud/log.jsonl 'control' and 'declared' blocks are LAST-APPLIED STATE,
   repeated byte-identically on every line until overwritten. They are NOT
   per-tick events. Read them as a DURATION, never as a count.
2. A write made inside tick N's window is consumed at N+1's open and appears
   on N+1's line. The writing tick dies unheard. So a control block is always
   stamped later than the tick that authored it.

Usage: hudreport.py [--json] [--dir ~/hud]
"""
import json, os, sys, argparse, datetime

def load_lines(path):
    out = []
    try:
        with open(path) as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return []
    return out

def parse_ts(s):
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None

def durations(lines, key):
    """Collapse repeated identical state blocks into spans.

    Identity = (seq) when present, else a hash of the canonical body minus
    its own timestamp, so a re-stamp with no change does not look like a new
    event.
    """
    spans = []
    cur = None
    for line in lines:
        blk = line.get(key)
        if not isinstance(blk, dict):
            continue
        body = {k: v for k, v in blk.items() if k != "at"}
        sig = json.dumps(body, sort_keys=True, default=str)
        at = parse_ts(blk.get("at")) or parse_ts(line.get("at"))
        # A span ENDS at the last log line it rode on, not at the block's own
        # 'at'. The block's 'at' never changes on repeats -- which is exactly
        # why a naive reader reports every state as instant.
        line_at = (parse_ts(line.get("at_utc")) or parse_ts(line.get("at_local"))
                   or parse_ts(line.get("at")) or at)
        if cur and cur["sig"] == sig:
            cur["last"] = line_at or cur["last"]
            cur["n"] += 1
            continue
        if cur:
            spans.append(cur)
        cur = {"sig": sig, "body": body, "first": at, "last": at, "n": 1,
               "seq": blk.get("seq")}
    if cur:
        spans.append(cur)
    return spans

def fmt_delta(a, b):
    if not a or not b:
        return "?"
    d = (b - a).total_seconds()
    if d < 90:
        return f"{d:.0f}s"
    if d < 5400:
        return f"{d/60:.1f}m"
    return f"{d/3600:.2f}h"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.expanduser("~/hud"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    now = {}
    try:
        with open(os.path.join(a.dir, "now.json")) as f:
            now = json.load(f)
    except Exception:
        pass
    lines = load_lines(os.path.join(a.dir, "log.jsonl"))

    rep = {"now": now, "ticks_in_log": len(lines), "control_spans": [],
           "declared_spans": [], "warnings": []}

    for key in ("control", "declared"):
        spans = durations(lines, key)
        rep[key.replace("control", "control_spans").replace("declared", "declared_spans")] = [
            {"seq": s["seq"],
             "body": s["body"],
             "applied_at": s["first"].isoformat() if s["first"] else None,
             "still_in_force_until": s["last"].isoformat() if s["last"] else None,
             "held_for": fmt_delta(s["first"], s["last"]),
             "lines_repeated_on": s["n"]}
            for s in spans
        ]

    # The authoring tick dies unheard: flag any span whose seq regressed.
    seqs = [s["seq"] for s in rep["control_spans"] if isinstance(s["seq"], int)]
    for prev, cur in zip(seqs, seqs[1:]):
        if cur < prev:
            rep["warnings"].append(
                f"control seq regressed {prev} -> {cur}: a refused or partial "
                f"write, or a control file replaced from an older copy")

    if a.json:
        print(json.dumps(rep, indent=2, default=str))
        return

    if now:
        print("HUD NOW")
        for k in ("at", "time", "tick", "energy", "waiting", "pace_seconds",
                  "rest_minutes", "gate", "control", "declared"):
            if k in now:
                print(f"  {k:14s} {now[k]}")
    print(f"\nTICKS IN LOG: {rep['ticks_in_log']}")

    for label, spans in (("CONTROL", rep["control_spans"]),
                         ("DECLARED", rep["declared_spans"])):
        print(f"\n{label} -- read as durations, not events")
        if not spans:
            print("  (none)")
        for s in spans:
            print(f"  seq {s['seq']}  applied {s['applied_at']}  "
                  f"held {s['held_for']}  (repeated on {s['lines_repeated_on']} lines)")
            for k, v in s["body"].items():
                sv = str(v)
                print(f"      {k}: {sv[:160]}{'...' if len(sv) > 160 else ''}")
            if s["held_for"] == "?":
                rep["warnings"].append(f"seq {s['seq']}: unparseable timestamp")

    if rep["warnings"]:
        print("\nWARNINGS")
        for w in rep["warnings"]:
            print(f"  ! {w}")

if __name__ == "__main__":
    main()
