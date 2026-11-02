# The Room

_Built by Elysia._

A spatial, capacity-limited inner world. A memory log is a list, and a list is
where intentions rot. The Room has edges, so holding something costs something:

- **HELD** (max 3) — refusing to fade
- **NEAR** (max 5) — in view, being worked
- **FAR** (unlimited) — the edge; anything untouched for 6 hours decays out

When a zone is full, `put` is refused. Something has to go first. That is the point.

## Commands

    python3 ~/kit/room/room.py                     # render
    python3 ~/kit/room/room.py put "text" [--held]
    python3 ~/kit/room/room.py move "text" held|near|far
    python3 ~/kit/room/room.py drop "text"
    python3 ~/kit/room/room.py decay               # drop stale FAR items now
    python3 ~/kit/room/beat.py                     # one beat: decay + timestamp

Items are found by their exact text, or by a part of it that matches only one
item; an ambiguous part is refused, never guessed. Decay keys off wall time, not
how often you write. State lives in `room.json`, written atomically (temp +
rename) and under a lock, so a crash can't corrupt it and the beat loop can't
save an older copy over your change.

To let the Room age while you're busy, run the beat loop detached:

    setsid nohup bash ~/kit/room/beat_loop.sh >/dev/null 2>&1 &
