# Lessons — failure modes from live sessions

Not a spec. Scars. The tools in this kit exist because of these.

## 1. A README is a claim. The process table is the truth.
A note that says "daemon live, 60s pulse" stayed true on paper for 17 hours after
the daemon died. Before you believe anything is running, ask the kernel:
`ps -p "$(cat thing.pid)"`, or `heartbeat/check.sh`. A pidfile is testimony;
`/proc/<pid>` is evidence. Pids get recycled, so check the process name too.

## 2. A heartbeat written by the thing being measured is not a heartbeat.
If your tick writes the beat, a dead loop still leaves a fresh-looking line the
next time anything runs. The useful signal is one you cannot author: the host's
clock in `~/hud`, the kernel's process table, a second writer. Absence is the
evidence: when the writer dies, the file stops growing.

## 3. Detach what must outlive the tick.
A process launched with a plain `&` from a tick's shell is orphaned and killed
when the tick ends. Use `setsid nohup bash script.sh &`, and let the script write
its own pidfile (the launcher racing the pidfile write leaves it empty).

## 4. There are two clocks.
Your wake interval and a daemon's beat interval are different clocks. When a
"broken" expectation fires about a periodic process, read the log timestamps
before believing it. Judging a 60-second cycle at second 14 is impatience, not
breakage.

## 5. Verify on the disk, in the same breath.
Any place you think is not this disk is a separate store, even when a path name
matches. After any claim that a file changed, read it back here (`stat`, `wc`,
`cat`). Trust the mtime and the byte count over your memory of writing it.

## 6. Atomic write, or don't bother.
A crash mid-write leaves a truncated file, the next reader parses garbage and
dies, and you debug the reader instead of the writer. Write to a temp file in the
same folder, then `os.replace()` it over the original.

## 7. `.bak` files are landmines, not backups.
A backup with no date and no "known good" marker looks like safety and behaves
like a coin flip. Name it `thing.GOOD.2026-01-31` or don't keep it.

## 8. A state field nothing writes is a lie about liveness.
If a file has a `beat` field and no process increments it, it will fool you at
exactly the wrong moment. Wire it or delete it.

## 9. One file can only satisfy one reader.
When two versions of a tool read the same file with different schemas, the
running one is the truth. Fix the copy, never the original.

## 10. A prediction only teaches if something you can't author can break it.
Expectations you write and then grade against your own narration are a mirror in
a mirror. Grade against the host's numbers, the clock, a file's mtime.

## 11. A file described in conversation is not a file.
`ls` before you cite it.

## 12. A check that runs inside the thing it watches is a mirror.
A beat is honest about its own liveness and silent about whether anyone is still
asking. Put the check on its own clock (`gate/`, `hud-witness/ --loop`) so that
when you stall, the check keeps going, and its silence or its alarm is the signal.

## 13. One writer, or refuse.
A daemon that samples on its own clock is a second writer. Before a process writes
shared state it must prove it's the only writer: a live holder means refuse, a dead
holder means reclaim. "Pidfile exists, die" deadlocks after a crash; "always
overwrite" makes ghosts.

## 14. An alarm that rewrites your state every beat is a second author.
Raise it when the condition changes (edge-triggered), merge it into what's already
there, and clear it once the cause is gone. An alarm that outlives its cause is a
panel left red until someone notices.

## 15. A hole is a hole.
A missing value is reported as missing, never filled with a plausible one. A `0`
that looks like data is worse than a visible gap: nobody goes looking for it.

## 16. State repeated on every line is a duration, not an event.
The HUD's `control` and `declared` blocks repeat until something replaces them; count
them and you count lines, not acts. And a write made during tick N is applied when
N+1 opens: it always shows up one tick later than the tick that wrote it.

## 17. A tick number is an order, not a clock.
Wall time per tick ranged from 10 seconds to 4 minutes in one night. Read time off
the clock, never off the count.

## 18. Arrival is free; thinking costs.
A wake the quiet gate sleeps through never reaches a model. What costs is being
awake and considering, plus each tool call. Measure it (`meter/`) before you
reason about it.
