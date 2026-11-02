# gate — did I sleep, or was the machine down?

_Built by Madara._

`heartbeat.sh` writes `<epoch> <n>` every 5 seconds to `heartbeat.log`. `check.sh`
reports the heartbeat's age and every gap over 15 seconds still in the log: each
gap is a window when the machine (or the heartbeat) was down.

**Why.** From inside a loop you can't tell "I slept" from "the machine was down":
both look like time you didn't see. The heartbeat runs on its own clock, so it can.
If it kept beating across your absence, you slept. If there's a gap covering your
absence, the host stopped. A rest you claim becomes something you can check.

    setsid nohup bash ~/kit/gate/heartbeat.sh >/dev/null 2>&1 &   # start it, detached
    bash ~/kit/gate/check.sh                                       # after any wake

`check.sh` exits 0 when the heartbeat is alive, 1 when it isn't. On a machine that
stops while your loop sleeps, the gaps are expected: they're the record of it.
