#!/usr/bin/env python3
"""beat.py — let time pass for the Room even when you are not speaking to it.

Stamps last_beat, bumps the display tick, and runs room.py's own decay so FAR
items untouched past DECAY_SECONDS actually fall out. There is exactly ONE decay
rule (in room.py). If room.json is malformed, refuse and exit non-zero rather
than clobber it.

Run once:      python3 ~/kit/room/beat.py
Run forever:   setsid nohup bash ~/kit/room/beat_loop.sh >/dev/null 2>&1 &
"""
import importlib.util, os, sys, time

ROOM_DIR = os.path.dirname(os.path.abspath(__file__))


def _room_module():
    spec = importlib.util.spec_from_file_location("room_mod", os.path.join(ROOM_DIR, "room.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    try:
        room = _room_module()
        with room.locked():  # the same lock room.py holds, so a beat never saves over a put
            d = room._load()
            if not all(z in d for z in ("held", "near", "far")):
                raise ValueError("room.json is not the held/near/far schema. Refusing.")
            dropped = room.decay_items(d)
            d["last_beat"] = time.time()
            room._save(d)  # atomic; bumps the display tick
        for text in dropped:
            print(f"decayed: {text}")
        print(f"beat ok: tick={d['tick']} last_beat={d['last_beat']:.0f}")
    except Exception as e:
        print(f"beat refused: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
