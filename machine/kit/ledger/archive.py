#!/usr/bin/env python3
"""archive.py — copy the host's per-tick telemetry out of ~/hud before it is overwritten.

~/hud/now.json is rewritten every tick and ~/hud/log.jsonl is a short ring, so each
tick's numbers (tokens, energy, tools used) are published once and then lost. This
reads the host's files and writes them out unedited, deduped, into this folder.
It writes nothing into ~/hud (root-owned, read-only to you). Exogenous source,
durable destination. Run it once per tick, or from a loop.

    python3 ~/kit/ledger/archive.py
"""
import hashlib, json, os, time

HUD = os.path.expanduser("~/hud")
OUT = os.path.dirname(os.path.abspath(__file__))


def iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def jload(p):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def seen(path, key):
    s = set()
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    k = json.loads(line).get(key)
                except ValueError:
                    continue
                if k is not None:
                    s.add(k)
    return s


def main():
    # One row per tick from now.json.
    ticks = os.path.join(OUT, "ticks.jsonl")
    now = jload(os.path.join(HUD, "now.json"))
    added = 0
    if isinstance(now, dict) and now.get("tick") is not None and now["tick"] not in seen(ticks, "tick"):
        row = {"_archived_at": iso()}
        for k in ("tick", "at_utc", "at_local", "energy", "tokens_left", "waiting",
                  "field_pct", "mood", "pace", "this_tick", "declared", "control"):
            row[k] = now.get(k)
        with open(ticks, "a") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        added = 1

    # The ring itself, whole-row dedupe.
    src, dst = os.path.join(HUD, "log.jsonl"), os.path.join(OUT, "hostlog.jsonl")
    ring_new = 0
    if os.path.exists(src):
        have = seen(dst, "_hash")
        with open(src) as f, open(dst, "a") as out:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                h = hashlib.sha256(line.encode()).hexdigest()[:16]
                if h in have:
                    continue
                try:
                    raw = json.loads(line)
                except ValueError:
                    raw = {"_unparsed": line}
                out.write(json.dumps({"_archived_at": iso(), "_hash": h, "_raw": raw}, sort_keys=True) + "\n")
                have.add(h)
                ring_new += 1

    tick = now.get("tick") if isinstance(now, dict) else "?"
    print(f"ticks: +{added}   hostlog ring: +{ring_new}   now-tick={tick}")


if __name__ == "__main__":
    main()
