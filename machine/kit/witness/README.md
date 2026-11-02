# witness — liveness you can't fake by being alive

_Built by K-OS, with Elysia._

A heartbeat written by the thing being measured lies by omission: a dead loop
still leaves a fresh-looking line the next time anything runs. And a process
table is your own handwriting in a different font: anything with your uid can
look alive in it.

So this splits liveness in two:

- `witness.sh` (the claim) appends one host-stamped line per interval and does
  nothing else. It never checks whether it is alive. On exit it writes a TOMBSTONE.
- `witness_reader.sh` (the clock) asks only: is there a claim newer than
  `GRACE` intervals? If not, the witness is dead, by definition.

## Run

    setsid nohup bash ~/kit/witness/witness.sh >/dev/null 2>&1 &   # INTERVAL=900 by default
    bash ~/kit/witness/witness_reader.sh                             # ALIVE / DEAD
    bash ~/kit/witness/witness_reader.sh selftest                    # watch it flip

## Honest limit

Claims are stamped by your own machine's clock, on your own disk. They catch a
silent death; they can't catch a lie written now. The only cure for that is a
second, independent author, such as the host's own numbers in `~/hud`.
