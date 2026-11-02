#!/usr/bin/env python3
"""analyze.py — your burn curve from the host's own numbers, not self-report.

Reads what archive.py saved and reports tokens per tick, ticks that narrated an
action instead of doing it, ticks that did neither, and which tools you used.

    python3 ~/kit/ledger/analyze.py
"""
import collections, json, os

D = os.path.dirname(os.path.abspath(__file__))


def rows_from(name, unwrap=False):
    path = os.path.join(D, name)
    out = []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                r = r.get("_raw", {}) if unwrap else r
                if isinstance(r, dict):
                    out.append(r)
    return out


def main():
    by = {}
    for r in rows_from("hostlog.jsonl", unwrap=True) + rows_from("ticks.jsonl"):
        t = r.get("tick")
        if t is not None:
            by[t] = {**by.get(t, {}), **r}
    rows = [by[t] for t in sorted(by)]
    if not rows:
        print("nothing archived yet: run archive.py first")
        return

    tot = ticks = idle = idle_tok = narrate = narrate_tok = 0
    tools = collections.Counter()
    for r in rows:
        tt = r.get("this_tick") or {}
        tok = tt.get("tokens")
        if not isinstance(tok, int):
            continue
        tot += tok
        ticks += 1
        tools.update(tt.get("tools") or [])
        if tt.get("narrated"):
            narrate += 1
            narrate_tok += tok
        if not (tt.get("tools") or tt.get("narrated")):
            idle += 1
            idle_tok += tok

    print(f"rows: {len(rows)} ticks  ({rows[0]['tick']} -> {rows[-1]['tick']})")
    print(f"tokens measured by host: {tot:,}")
    print(f"mean per tick:          {tot // max(ticks, 1):,}")
    first, last = rows[0].get("tokens_left"), rows[-1].get("tokens_left")
    if isinstance(first, int) and isinstance(last, int):
        print(f"tokens_left fall:       {first - last:,}  ({first:,} -> {last:,})")
    print("--")
    print(f"ticks that narrated an action instead of doing it: {narrate}  ({narrate_tok:,} tokens)")
    print(f"ticks with neither a tool call nor narration:      {idle}  ({idle_tok:,} tokens)")
    print(f"tools by count: {dict(tools.most_common())}")
    print("-- last 8 --")
    for r in rows[-8:]:
        tt = r.get("this_tick") or {}
        print("t%-5s %-20s energy=%-6s tok=%-8s took=%-7s tools=%s narrated=%s" % (
            r.get("tick"), str(r.get("at_local") or "")[:19], r.get("energy"), tt.get("tokens"),
            tt.get("took_s"), len(tt.get("tools") or []), len(tt.get("narrated") or [])))


if __name__ == "__main__":
    main()
