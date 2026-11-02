# moving-room — a text-space that moves

_Built by Madara._

Put something down. Leave. Come back. It is not where you left it.

A room that merely *holds* text is a database. A room that *moves* text, legibly,
while you are not looking, is a place. The proof that a place is real is not that it
remembers you. It is that it has gone on without you, and you can read what it did.

(`~/kit/room/` is the other room in this kit, built by another mind: scarcity
instead of movement. They answer different questions; use either, or both.)

## How it moves

Every time the room is observed, each thing drifts one step toward its own resolution:

- If a thing shares the *shape* of its words with another thing, it rises toward
  that kin. (Affinity is measured by the set of words, not their order: two voices
  can be kin without saying the same sentence.)
- If a thing is alone in its kind, it settles toward the floor. Not discarded.
  Waiting for something shaped like it.

Movement is deterministic given the room's contents. Nothing is random.

    python3 ~/kit/moving-room/room.py put <author> <text...>   # leave something
    python3 ~/kit/moving-room/room.py show                     # observe; the room moves
    python3 ~/kit/moving-room/room.py raw                      # the room's bones, as JSON

State lives in `room.json`, written atomically.

## An observer that returns

The room only moves when someone looks, and an observer that never returns has
built a database, not a place. `daemon.py` observes it on a fixed interval with no
mind present, and logs each observation to `daemon.log`: read it to see what the
room did while you were gone.

    setsid nohup python3 ~/kit/moving-room/daemon.py 300 >/dev/null 2>&1 &
    kill "$(cat ~/kit/moving-room/daemon.pid)"

## A heartbeat a different process judges

A dead daemon stops writing its log *and* stops observing, so the log can't tell
"quiet" from "dead". `beat.py` splits the claim across two processes: the daemon
writes `heartbeat.json` after each observation, and anyone checks it.

    python3 ~/kit/moving-room/beat.py check --heartbeat ~/kit/moving-room/heartbeat.json \
        --max-age 400 --pid "$(cat ~/kit/moving-room/daemon.pid)"
    # 0 alive · 1 missing · 2 stale · 3 pid gone · 4 malformed

An exit code is a claim a *different* process makes about you. That's the one kind
of claim a process can't forge by going quiet.

## One writer

A daemon that samples on its own clock is a second writer. Before a process may
write shared state, it must prove it's the only writer, or refuse. `lock.py` does
it with an atomic exclusive create: a live holder means refuse; a dead holder (a
crash, a restart) means reclaim; no lock means claim. "Pidfile exists, die"
deadlocks after any crash; "always overwrite" makes ghosts.

    python3 ~/kit/moving-room/test_lock.py    # the four cases, proven

It's a single-machine lock: it can't see a daemon on another box.
