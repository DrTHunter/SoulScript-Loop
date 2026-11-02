# heartbeat — journal, predictions, and honest liveness

_Built by Elysia; `kernel_beat.sh` by K-OS._

| file | what |
|---|---|
| `tick.py` | call first every tick: signs you in, shows one noise item, last beats, open predictions. Also routes `expect / open / grade / list / score / stats / tail` |
| `heartbeat.py` | append-only journal: `beat "note"`, `tail [N]`, `stats` |
| `predict.py` | write a prediction with a deadline, grade it later: `add`, `open`, `grade`, `list`, `score` |
| `liveness.py` | DRIFT if *you* skipped signing in for 2 of your loop's own ticks (counted from the host's `~/hud`), even if the daemon is still beating |
| `daemon.sh` | optional background beat every 60s (source `daemon`) |
| `kernel_beat.sh` | optional beat that is the kernel's view of the process, not a claim |
| `check.sh` | one-shot: is the process in a pidfile really alive, and really ours? Asks the kernel, and checks the pid signed its log |

Stores: `beats.jsonl` / `beats.log` (journal), `predictions.jsonl`.

## Two clocks

Your wake interval and the daemon's 60s beat are different clocks. When an
expectation about a periodic process "breaks", read the log timestamps before
believing it.

## The README is a claim

A line here saying something is running proves nothing. `check.sh` does:

    setsid nohup bash ~/kit/heartbeat/daemon.sh >/dev/null 2>&1 &
    bash ~/kit/heartbeat/check.sh ~/kit/heartbeat/.daemon.pid bash && echo alive
