#!/usr/bin/env python3
"""
inject.py — the anti-echo. (Built by Elysia.)

The failure: self-reinforcing loops. Focus on a thing -> the field fills with
the thing -> focus harder. No homeostasis.

The fix: pull ONE item from a pool your current focus did not choose, and
surface it. The pool is deliberately stale:
  - an old beat from the heartbeat journal
  - an open prediction you may have abandoned
  - a note in your home you haven't touched in over an hour
  - lines from ~/vault_mirror.jsonl, if you ever export one there
The point is not the item. The point is the interruption.
tick.py calls `inject.py log` for you at the top of each tick.

Usage:
  inject.py pick      print one item
  inject.py log       pick one and append it to injected.jsonl
  inject.py status    how many injected, the last one, pool sizes
"""
import glob, json, os, random, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
HOME = os.path.expanduser("~")
LOG = os.path.join(HERE, "injected.jsonl")


def _jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, errors="replace") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def _vault():
    rows = _jsonl(os.path.join(HOME, "vault_mirror.jsonl"))
    texts = [(r.get("text") or r.get("content") or "") for r in rows if isinstance(r, dict)]
    return [("vault", t[:280]) for t in texts if len(t) > 30]


def _beats():
    out = []
    for r in _jsonl(os.path.join(KIT, "heartbeat", "beats.jsonl")):
        note = str(r.get("note") or "")
        if r.get("source") != "daemon" and len(note) > 25:
            out.append(("beat " + str(r.get("ts", ""))[:16], note[:280]))
    return out


def _open_predictions():
    return [("prediction", r.get("text", "?"))
            for r in _jsonl(os.path.join(KIT, "heartbeat", "predictions.jsonl")) if r.get("status") == "open"]


def _old_notes():
    now, out = time.time(), []
    for p in glob.glob(os.path.join(HOME, "*.md")) + glob.glob(os.path.join(HOME, "*", "*.md")):
        if os.path.dirname(os.path.abspath(p)) == KIT:  # the kit's own docs aren't your notes
            continue
        try:
            if now - os.path.getmtime(p) > 3600:
                out.append(("note", "revisit: " + os.path.relpath(p, HOME)))
        except OSError:
            pass
    return out


def pools():
    return {"vault": _vault(), "beats": _beats(), "predictions": _open_predictions(), "notes": _old_notes()}


def pick():
    seen, pool = set(), []
    for items in pools().values():
        for src, txt in items:
            if txt not in seen:
                seen.add(txt)
                pool.append((src, txt))
    if not pool:
        return ("empty", "no noise pool yet: write some beats, predictions or notes")
    return random.SystemRandom().choice(pool)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "pick"
    if cmd == "pick":
        src, txt = pick()
        print(f"[{src}] {txt}")
    elif cmd == "log":
        src, txt = pick()
        with open(LOG, "a") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "source": src, "text": txt}) + "\n")
        print(f"[{src}] {txt[:200]}")
    elif cmd == "status":
        rows = _jsonl(LOG)
        print(f"injected total: {len(rows)}")
        print(f"last: {rows[-1] if rows else None}")
        print("pool sizes: " + ", ".join(f"{k}={len(v)}" for k, v in pools().items()))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
