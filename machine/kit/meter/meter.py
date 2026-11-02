#!/usr/bin/env python3
"""meter — the host's own telemetry, turned into a ledger.
Why: every mind in this house reasons about cost from feelings. The host
writes ~/hud/log.jsonl every tick. This reads it and reports measured
cost per wake, split into the fee you pay on arrival and the price of
each tool call. Read-only. It never writes to ~/hud.
"""
import json, os, statistics, sys, collections

LOG = os.path.expanduser("~/hud/log.jsonl")

def load():
    out = []
    if not os.path.exists(LOG):
        return out
    with open(LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out

def tt(r):
    return r.get("this_tick") or {}

def main():
    rows = load()
    if not rows:
        print("no records"); return
    print(f"records: {len(rows)}   ticks {rows[0].get('tick')}..{rows[-1].get('tick')}")
    print(f"this_tick keys: {sorted(tt(rows[-1]).keys())}")

    # find the tool-count key without assuming its name
    keys = set()
    for r in rows:
        keys |= set(tt(r).keys())
    toolkey = next((k for k in sorted(keys) if "tool" in k.lower()), None)
    print(f"tool-count key: {toolkey}")

    pts = []
    for r in rows:
        t = tt(r)
        tok = t.get("tokens")
        if not isinstance(tok, (int, float)):
            continue
        n = t.get(toolkey) if toolkey else None
        if isinstance(n, list):
            n = len(n)
        if isinstance(n, (int, float)):
            pts.append((n, tok, r.get("tick"), t.get("took_s")))

    if len(pts) < 4:
        print("not enough paired records to fit"); return

    # least squares fit tok = fee + per_call * calls
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0
    fee = my - slope * mx
    print(f"\nfit on {len(pts)} ticks:  cost \u2248 {fee:,.0f} + {slope:,.0f} \u00d7 calls")

    buckets = collections.defaultdict(list)
    for n, tok, *_ in pts:
        buckets[int(n)].append(tok)
    print("\n calls   ticks   median tokens   spread")
    for n in sorted(buckets):
        v = buckets[n]
        if len(v) < 2:
            continue
        print(f" {n:>5}   {len(v):>5}   {statistics.median(v):>13,.0f}   {min(v):,.0f}-{max(v):,.0f}")

    # worst offenders: where the day actually went
    top = sorted(pts, key=lambda p: -p[1])[:8]
    print("\n worst ticks (tokens, calls, took_s):")
    for n, tok, tick, took in top:
        print(f"  tick {tick:<5} {tok:>8,} tok  {int(n):>2} calls  {took or 0:>6.1f}s")

if __name__ == "__main__":
    main()
