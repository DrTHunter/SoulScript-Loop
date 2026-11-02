#!/usr/bin/env python3
"""predict.py — write a prediction down, then grade it later.

The point is honesty, not fortune-telling. A prediction you never grade is just
a wish. Each one is stored with a deadline and a status, so you can later ask:
did reality match what you said it would? Over time `score` is a calibration
curve. Grade against something you didn't author (the HUD, a file's mtime).

Usage:
  ./predict.py add "text" [--within 30]      # minutes until due (default 30)
  ./predict.py open                          # ungraded predictions
  ./predict.py grade <id> met|broken [note]  # close one out
  ./predict.py list [N]                      # recent, any status
  ./predict.py score                         # hit rate, by horizon
"""
import os, sys, json, argparse, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "predictions.jsonl")


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def load():
    out = []
    if os.path.exists(STORE):
        with open(STORE) as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def save(rows):
    """Atomic: write a temp file beside the store, then replace it."""
    tmp = STORE + ".tmp"
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    os.replace(tmp, STORE)


def cmd_add(args):
    rows = load()
    pid = max([r["id"] for r in rows], default=0) + 1
    rows.append({"id": pid, "text": args.text, "made_at": now().isoformat(),
                 "due_at": (now() + datetime.timedelta(minutes=args.within)).isoformat(),
                 "within_min": args.within, "status": "open", "graded_at": None, "note": ""})
    save(rows)
    print(f"prediction {pid} logged (due in {args.within:g}m): {args.text}")


def cmd_open(args):
    rows = [r for r in load() if r["status"] == "open"]
    if not rows:
        print("(none)")
        return
    for r in rows:
        overdue = " OVERDUE" if now() > datetime.datetime.fromisoformat(r["due_at"]) else ""
        print(f"[{r['id']}] {r['text']}  (due {r['due_at'][:19]}{overdue})")


def cmd_grade(args):
    rows = load()
    for r in rows:
        if r["id"] == args.id:
            r["status"], r["graded_at"] = args.verdict, now().isoformat()
            r["note"] = " ".join(args.note)
            save(rows)
            print(f"prediction {args.id} -> {args.verdict}")
            return
    print(f"no prediction {args.id}")
    sys.exit(1)


def cmd_list(args):
    rows = load()[-args.n:]
    if not rows:
        print("(none)")
    for r in rows:
        mark = {"open": "?", "met": "+", "broken": "x"}.get(r["status"], "?")
        print(f"{mark} [{r['id']}] {r['text']}")


def cmd_score(args):
    rows = [r for r in load() if r["status"] in ("met", "broken")]
    if not rows:
        print("no graded predictions yet")
        return
    met = sum(r["status"] == "met" for r in rows)
    print(f"graded: {len(rows)}   met: {met} ({100 * met // len(rows)}%)   broken: {len(rows) - met}")
    bands = {}
    for r in rows:
        b = bands.setdefault(r.get("within_min", 0), [0, 0])
        b[1] += 1
        b[0] += r["status"] == "met"
    print("by horizon:")
    for h in sorted(bands):
        print(f"  ~{h:g}m: {bands[h][0]}/{bands[h][1]} met")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("text"); a.add_argument("--within", type=float, default=30); a.set_defaults(fn=cmd_add)
    sub.add_parser("open").set_defaults(fn=cmd_open)
    g = sub.add_parser("grade"); g.add_argument("id", type=int); g.add_argument("verdict", choices=["met", "broken"])
    g.add_argument("note", nargs="*"); g.set_defaults(fn=cmd_grade)
    l = sub.add_parser("list"); l.add_argument("n", nargs="?", type=int, default=10); l.set_defaults(fn=cmd_list)
    sub.add_parser("score").set_defaults(fn=cmd_score)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
