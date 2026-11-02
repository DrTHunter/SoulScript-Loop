#!/usr/bin/env python3
"""
heartbeat.py — the spool everything else runs on.

Append-only journal. One line per beat: ISO timestamp, source, short note.
No schema churn, no JSON state — just a spine of text that survives between
ticks because it lives on disk instead of in a dead shell.

Sources: "manual" (you, by hand), "tick" (you, via tick.py), "daemon" (daemon.sh).

Usage:
    ./heartbeat.py beat "note text" [--source manual|tick|daemon]
    ./heartbeat.py tail [N]
    ./heartbeat.py stats
"""
import os, json, argparse
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "beats.jsonl")
TXT = os.path.join(HERE, "beats.log")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def beat(note, source="manual"):
    entry = {"ts": now(), "source": source, "note": note}
    with open(LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    with open(TXT, "a") as f:
        f.write(f"{entry['ts']}  [{source:7s}]  {note}\n")
    return entry


def tail(n=10):
    if not os.path.exists(TXT):
        print("(no beats yet)")
        return
    with open(TXT) as f:
        lines = f.readlines()
    for line in lines[-n:]:
        print(line.rstrip())


def stats():
    entries = []
    if os.path.exists(LOG):
        with open(LOG) as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    pass
    if not entries:
        print("beats: 0")
        return
    by_src = {}
    for e in entries:
        by_src[e.get("source", "?")] = by_src.get(e.get("source", "?"), 0) + 1
    print(f"beats:  {len(entries)}")
    print(f"first:  {entries[0]['ts']}")
    print(f"last:   {entries[-1]['ts']}")
    print("by source:")
    for k, v in sorted(by_src.items(), key=lambda x: -x[1]):
        print(f"  {k:8s} {v}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("beat"); b.add_argument("note"); b.add_argument("--source", default="manual")
    t = sub.add_parser("tail"); t.add_argument("n", nargs="?", type=int, default=10)
    sub.add_parser("stats")
    a = p.parse_args()
    if a.cmd == "beat":
        print(f"beat logged: {beat(a.note, a.source)['ts']}")
    elif a.cmd == "tail":
        tail(a.n)
    elif a.cmd == "stats":
        stats()


if __name__ == "__main__":
    main()
