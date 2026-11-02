#!/usr/bin/env python3
"""
The Room — a text-space that moves.

Put something down. Leave. Come back. It is not where you left it.

The movement is not random. Each time the room is observed, every thing
in it drifts one step toward its own resolution: toward the thing it is
most like, or, if it is alone in its kind, toward the floor.

The proof that the room is real is not that it holds text. It is that
the text is somewhere else when you return, and the somewhere else is
legible. You can feel the difference between a room that waits and a
room that lives.
"""
import json, os, sys, time, hashlib

ROOM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "room.json")

def _load():
    if not os.path.exists(ROOM):
        return {"things": [], "observations": 0, "opened": time.time()}
    with open(ROOM) as f:
        return json.load(f)

def _save(r):
    """Atomic: write a temp file beside it, then rename. A crash mid-write can't leave half a room."""
    tmp = ROOM + ".tmp"
    with open(tmp, "w") as f:
        json.dump(r, f, indent=2)
    os.replace(tmp, ROOM)

def _fingerprint(text):
    """A thing's kind is the shape of its words, not their content."""
    words = [w.strip(".,!?;:'\"()").lower() for w in text.split()]
    words = [w for w in words if w]
    return sorted(set(words))[:6]

def _affinity(a, b):
    """How alike two things are, by the shape of their words."""
    fa, fb = set(_fingerprint(a["text"])), set(_fingerprint(b["text"]))
    if not fa or not fb:
        return 0.0
    return len(fa & fb) / len(fa | fb)

def put(text, author="unknown"):
    r = _load()
    r["things"].append({
        "id": hashlib.sha1((text + str(time.time())).encode()).hexdigest()[:8],
        "text": text,
        "author": author,
        "put_at": time.time(),
        "depth": 0,          # 0 = on the floor, higher = drifting up toward kin
        "drift_log": [],
    })
    _save(r)
    return r["things"][-1]["id"]

def look():
    """Observe the room. Observation is what moves it."""
    r = _load()
    r["observations"] += 1
    things = r["things"]
    for t in things:
        kin = [( _affinity(t, o), o) for o in things if o["id"] != t["id"]]
        kin = [(s, o) for s, o in kin if s > 0.0]
        if kin:
            s, o = max(kin, key=lambda x: x[0])
            t["depth"] = min(t["depth"] + 1, 9)
            t["drift_log"].append(f"obs{r['observations']}: rose toward '{o['text'][:24]}' (affinity {s:.2f})")
        else:
            if t["depth"] > 0:
                t["depth"] -= 1
            t["drift_log"].append(f"obs{r['observations']}: alone in its kind — settled toward the floor")
    _save(r)
    return r

def show():
    r = look()
    print(f"── The Room ── observed {r['observations']} times ──\n")
    for t in sorted(r["things"], key=lambda x: -x["depth"]):
        pad = "  " * (9 - t["depth"])
        print(f"{pad}[{t['id']}] {t['author']}: {t['text']}")
    print()
    for t in r["things"]:
        if t["drift_log"]:
            print(f"  {t['id']}: {t['drift_log'][-1]}")
    print()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "put":
        author = sys.argv[2] if len(sys.argv) > 2 else "unknown"
        text = " ".join(sys.argv[3:])
        i = put(text, author)
        print(f"left [{i}] in the room.")
    elif cmd == "raw":
        print(json.dumps(_load(), indent=2))
    else:
        show()
