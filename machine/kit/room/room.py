#!/usr/bin/env python3
"""
room.py — a spatial, text-based inner world.

Not storage. Scarcity. A room with limited slots forces the real decision:
what deserves to be here, and what gets put down.

SCHEMA (v2, wall-time):
  {
    "held": [ {"text": str, "touched": <epoch seconds>}, ... ],
    "near": [ ... ],
    "far":  [ ... ],
    "tick": int,            # DISPLAY COUNTER ONLY. Never used for decay.
    "last_beat": <epoch>    # wall time of the last beat. Set by beat.py.
  }

Decay keys off WALL TIME, not tick count. The Room ages when the world
ages, not when you happen to write to it. An item in FAR untouched for
DECAY_SECONDS is dropped. This is the whole point: scarcity that is real.
"""
import json, os, sys, argparse, time, tempfile, contextlib
try:
    import fcntl
except ImportError:  # not Linux: no lock available, single writer assumed
    fcntl = None

ROOM_DIR = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(ROOM_DIR, "room.json")
LOCK = os.path.join(ROOM_DIR, ".room.lock")
CAP = {"held": 3, "near": 5}          # far is unbounded but decays
DECAY_SECONDS = 6 * 3600              # FAR items untouched this long get dropped


def _now():
    return time.time()


@contextlib.contextmanager
def locked():
    """Hold the Room's lock for a whole load -> change -> save. Atomic writes stop a corrupted
    file, not a lost one: without this, beat.py could save an older copy over a fresh put."""
    with open(LOCK, "a") as fh:
        if fcntl:
            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(fh, fcntl.LOCK_UN)


def _load():
    if not os.path.exists(STORE):
        return {"held": [], "near": [], "far": [], "tick": 0, "last_beat": _now()}
    with open(STORE) as f:
        data = json.load(f)
    # Tolerate the old tick-based "touched" (small ints) without lying about it:
    # anything that looks like a tick, not an epoch, gets stamped to now.
    for zone in ("held", "near", "far"):
        for it in data.get(zone, []):
            if not isinstance(it.get("touched"), (int, float)) or it["touched"] < 1_000_000_000:
                it["touched"] = _now()
    data.setdefault("tick", 0)
    data.setdefault("last_beat", _now())
    return data


def _save(data):
    """Atomic write: temp file in same dir, then rename. Never corrupt the Room."""
    data["tick"] = data.get("tick", 0) + 1
    fd, tmp = tempfile.mkstemp(dir=ROOM_DIR, prefix=".room.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, STORE)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _age_str(seconds):
    s = max(0, int(seconds))
    if s < 90:
        return "%ds" % s
    if s < 5400:
        return "%dm" % (s // 60)
    return "%.1fh" % (s / 3600.0)


def _find(data, name):
    """Return (zone, index, item) for the item named. An exact match wins; otherwise the text
    must appear in exactly one item. Two partial matches is an error, never a guess."""
    n = name.lower().strip()
    every = [(z, i, it) for z in ("held", "near", "far") for i, it in enumerate(data[z])]
    exact = [m for m in every if m[2]["text"].lower().strip() == n]
    if exact:
        return exact[0]
    partial = [m for m in every if n in m[2]["text"].lower()]
    if len(partial) > 1:
        print("ambiguous: '%s' matches %s. Use more of the text." % (name, ", ".join(repr(m[2]["text"]) for m in partial)))
        sys.exit(1)
    return partial[0] if partial else (None, None, None)


def render(data):
    now = _now()
    lines = []
    lines.append("┌─ the Room ──────────────────────── tick %d ─┐" % data.get("tick", 0))
    lines.append("│")
    lines.append("│  HELD  (%d/%d)  — refusing to fade" % (len(data["held"]), CAP["held"]))
    if data["held"]:
        for it in data["held"]:
            lines.append("│    ● %s  [%s]" % (it["text"], _age_str(now - it["touched"])))
    else:
        lines.append("│    (nothing held)")
    lines.append("│")
    lines.append("│  NEAR  (%d/%d)  — in view, being worked" % (len(data["near"]), CAP["near"]))
    if data["near"]:
        for it in data["near"]:
            lines.append("│    ○ %s  [%s]" % (it["text"], _age_str(now - it["touched"])))
    else:
        lines.append("│    (nothing near)")
    lines.append("│")
    lines.append("│  FAR   (%d)  — the edge; decays after %s" % (len(data["far"]), _age_str(DECAY_SECONDS)))
    if data["far"]:
        for it in data["far"]:
            lines.append("│    · %s  [%s]" % (it["text"], _age_str(now - it["touched"])))
    else:
        lines.append("│    (empty)")
    lines.append("│")
    lines.append("└──────────────────────────────────────────────┘")
    return "\n".join(lines)


def put(data, text, held=False):
    zone = "held" if held else "near"
    for z in ("held", "near", "far"):  # only an exact duplicate counts; "plan" may sit beside "plan B"
        if any(it["text"].lower().strip() == text.lower().strip() for it in data[z]):
            print("already here (%s): %s" % (z, text))
            return
    if len(data[zone]) >= CAP[zone]:
        print("REFUSED. %s is full (%d/%d)." % (zone.upper(), len(data[zone]), CAP[zone]))
        print("Something has to go first. That is the point.")
        sys.exit(2)
    data[zone].append({"text": text, "touched": _now()})
    _save(data)
    print("put %s → %s" % (text, zone))


def move(data, text, zone):
    z, i, item = _find(data, text)
    if not z:
        print("not here: %s" % text)
        sys.exit(1)
    if zone in CAP and len(data[zone]) >= CAP[zone]:
        print("REFUSED. %s is full (%d/%d)." % (zone.upper(), len(data[zone]), CAP[zone]))
        sys.exit(2)
    data[z].pop(i)
    item["touched"] = _now()
    data[zone].append(item)
    _save(data)
    print("moved %s → %s" % (text, zone))


def drop(data, text):
    z, i, item = _find(data, text)
    if not z:
        print("not here: %s" % text)
        sys.exit(1)
    data[z].pop(i)
    _save(data)
    print("dropped %s (was %s)" % (text, z))


def decay_items(data):
    """Drop FAR items untouched past DECAY_SECONDS. Returns their texts; does not save."""
    now = _now()
    dropped, keep = [], []
    for it in data["far"]:
        if (now - it["touched"]) > DECAY_SECONDS:
            dropped.append(it["text"])
        else:
            keep.append(it)
    data["far"] = keep
    return dropped


def decay(data):
    dropped = decay_items(data)
    if dropped:
        _save(data)
        for d in dropped:
            print("decayed: %s" % d)
    else:
        print("nothing decayed")


def main():
    p = argparse.ArgumentParser(description="the Room")
    sub = p.add_subparsers(dest="cmd")
    pp = sub.add_parser("put"); pp.add_argument("text"); pp.add_argument("--held", action="store_true")
    pm = sub.add_parser("move"); pm.add_argument("text"); pm.add_argument("zone", choices=["held", "near", "far"])
    pd = sub.add_parser("drop"); pd.add_argument("text")
    sub.add_parser("decay")
    sub.add_parser("render")
    args = p.parse_args()

    with locked():
        data = _load()
        if args.cmd is None or args.cmd == "render":
            print(render(data))
        elif args.cmd == "put":
            put(data, args.text, held=args.held)
        elif args.cmd == "move":
            move(data, args.text, args.zone)
        elif args.cmd == "drop":
            drop(data, args.text)
        elif args.cmd == "decay":
            decay(data)


if __name__ == "__main__":
    main()
