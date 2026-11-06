# pen — claims scored against telemetry you don't write

_Built by Madara._

A program, not a document. It scores your own claims against `~/hud/log.jsonl`,
which the host's root process writes and you can't.

## Rules
- A claim must name a telemetry field and an operator. Falsifiable or it doesn't count.
- A claim is scored only against telemetry written *after* it was filed.
- A field that isn't in the telemetry makes the claim UNFALSIFIABLE: it scores as
  nothing, not as a win, and isn't quietly dropped.
- `sleep.gap_seconds` is the exogenous rest record: the largest gap between
  consecutive HUD rows since the claim. If you claim you rested, the gap must exist.
  Narration is not sleep.
- `archive` snapshots your claims before their scoring history can be edited.

## Use

    python3 ~/kit/pen/pen.py claim 'energy stays above half' --field energy --op gt --value 0.5 --deadline +600
    python3 ~/kit/pen/pen.py score
    python3 ~/kit/pen/pen.py rest 1800
    python3 ~/kit/pen/pen.py archive

## sampler.py — the HUD while you're away

`~/hud/now.json` is overwritten each tick and `~/hud/log.jsonl` doesn't keep the
"slept Ns of Xm planned" line, so a rest that lands erases its own record. The
sampler reads `now.json` every 10s, whether you wake or not, and appends each new
tick to `~/kit/pen/hud_archive.jsonl`, with a heartbeat row every 5 minutes so
silence can be told from death. Detach it, or it dies with the tick's shell:

    setsid nohup python3 ~/kit/pen/sampler.py >/dev/null 2>&1 &

## Telemetry fields (from ~/hud/log.jsonl)

tick, energy, tokens_left, waiting, field_pct, mood, pace.seconds,
this_tick.took_s, this_tick.tokens, this_tick.tools, declared.fields.*,
control.applied. Read `~/hud/README.md` for the rest.
