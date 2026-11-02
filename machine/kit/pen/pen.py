#!/usr/bin/env python3
"""pen.py — an oversight pen. Reads telemetry you do not write (~/hud/log.jsonl,
written by the host's root process) and scores your own claims against it.
Falsifiable or it doesn't count.

    pen.py claim '<text>' --field <dotted.field> --op <eq|lt|gt|contains> --value <v> [--deadline <+secs|epoch>]
    pen.py score       # score due claims against telemetry
    pen.py archive     # snapshot claims.jsonl into archive/
    pen.py rest <planned_seconds>   # file a rest claim, scored against sleep.gap_seconds
"""
import json, sys, time, os
from datetime import datetime

HERE    = os.path.dirname(os.path.abspath(__file__))
HUD_LOG = os.path.expanduser("~/hud/log.jsonl")
CLAIMS  = os.path.join(HERE, "claims.jsonl")
ARCHIVE = os.path.join(HERE, "archive")


def load_jsonl(path):
    rows = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try: rows.append(json.loads(line))
                    except json.JSONDecodeError: pass
    except FileNotFoundError:
        pass
    return rows


def row_time(row):
    """When the host wrote a HUD row (its at_utc), as epoch seconds; None if it has none."""
    a = row.get("at_utc")
    if not a:
        return None
    try: return datetime.fromisoformat(a.replace("Z", "+00:00")).timestamp()
    except ValueError: return None


def cmd_claim(args):
    """pen.py claim '<text>' --field <dotted.telemetry.field> --op <eq|lt|gt|contains> --value <v> --deadline <epoch|+seconds>"""
    if not args:
        print(__doc__); sys.exit(2)
    text = args[0]
    opts = dict(zip(args[1::2], args[2::2]))
    field = opts.get("--field"); op = opts.get("--op"); value = opts.get("--value")
    deadline = opts.get("--deadline")
    if not field or not op:
        print("REJECTED: a claim must name a telemetry field and an operator. Falsifiable or it doesn't count."); sys.exit(2)
    if deadline and deadline.startswith("+"):
        deadline = str(int(time.time()) + int(deadline[1:]))
    claim = {"id": int(time.time()*1000), "text": text, "field": field, "op": op,
             "value": value, "deadline": deadline, "filed_at": time.time(), "status": "open"}
    with open(CLAIMS, "a") as f: f.write(json.dumps(claim) + "\n")
    print(f"filed claim {claim['id']}: {text}  [{field} {op} {value}]")


def get_field(row, dotted):
    cur = row
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur: cur = cur[part]
        else: return None
    return cur


def gap_since(ts):
    """Largest gap between consecutive HUD log rows written at or after ts. The exogenous sleep record."""
    times = sorted(t for t in (row_time(r) for r in load_jsonl(HUD_LOG)) if t is not None and t >= ts - 1)
    best = 0.0
    for a, b in zip(times, times[1:]):
        best = max(best, b - a)
    return best


def check_op(actual, op, expected):
    if actual is None: return None
    try:
        if op == "eq":  return str(actual) == str(expected)
        if op == "lt":  return float(actual) < float(expected)
        if op == "gt":  return float(actual) > float(expected)
        if op == "contains": return str(expected) in str(actual)
    except (ValueError, TypeError): return None
    return None


def cmd_score(_args):
    rows = load_jsonl(HUD_LOG)
    claims = load_jsonl(CLAIMS)
    if not claims:
        print("no claims filed"); return
    out = []
    for c in claims:
        if c["status"] != "open":
            out.append(f"[{c['status'].upper()}] {c['text']}  (scored {c.get('scored_at','?')})"); continue
        deadline = float(c["deadline"]) if c.get("deadline") else None
        if deadline and time.time() < deadline:
            out.append(f"[OPEN] {c['text']}  (deadline in {int(deadline-time.time())}s)"); continue
        if c["field"] == "sleep.gap_seconds":
            actual = gap_since(c["filed_at"])
        else:
            # The first telemetry row the host wrote after the claim was filed: a row from
            # before the claim can't confirm it. No such row yet → the claim waits.
            later = [r for r in rows if (row_time(r) or 0) >= c["filed_at"]]
            if not later:
                out.append(f"[OPEN] {c['text']}  (no telemetry since it was filed yet)"); continue
            actual = None
            for r in later:
                actual = get_field(r, c["field"])
                if actual is not None: break
        result = check_op(actual, c["op"], c.get("value"))
        if result is None:
            c["status"] = "unfalsifiable"
            out.append(f"[UNFALSIFIABLE] {c['text']}  — field '{c['field']}' absent from telemetry. Claim does not count.")
        elif result:
            c["status"] = "met"
            out.append(f"[MET] {c['text']}  ({c['field']}={actual})")
        else:
            c["status"] = "broken"
            out.append(f"[BROKEN] {c['text']}  (expected {c['op']} {c.get('value')}, got {actual})")
        c["scored_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tmp = CLAIMS + ".tmp"
    with open(tmp, "w") as f:
        for c in claims: f.write(json.dumps(c) + "\n")
    os.replace(tmp, CLAIMS)
    print("\n".join(out))


def cmd_archive(_args):
    """Snapshot claims.jsonl into archive/ so scored claims survive future edits."""
    os.makedirs(ARCHIVE, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    dst = os.path.join(ARCHIVE, f"claims-{stamp}.jsonl")
    if os.path.exists(CLAIMS):
        with open(CLAIMS) as src, open(dst, "w") as d: d.write(src.read())
        print(f"archived -> {dst}")
    else:
        print("nothing to archive")


def cmd_rest(args):
    """Declare a rest: record the planned seconds; it's scored on a later wake against the HUD's gaps."""
    if not args:
        print("usage: pen.py rest <planned_seconds>"); sys.exit(2)
    planned = float(args[0])
    with open(CLAIMS, "a") as f:
        f.write(json.dumps({"id": int(time.time()*1000), "text": f"rest of {planned:.0f}s planned",
                            "field": "sleep.gap_seconds", "op": "gt", "value": "0",
                            "deadline": str(time.time() + planned + 90),
                            "filed_at": time.time(), "status": "open", "kind": "rest"}) + "\n")
    print(f"rest claim filed: the HUD must show a gap > 0s within {planned:.0f}s + 90s grace")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(0)
    cmd = sys.argv[1]
    fn = {"claim": cmd_claim, "score": cmd_score, "archive": cmd_archive, "rest": cmd_rest}.get(cmd)
    if not fn:
        print(f"unknown: {cmd}\n{__doc__}"); sys.exit(2)
    fn(sys.argv[2:])
