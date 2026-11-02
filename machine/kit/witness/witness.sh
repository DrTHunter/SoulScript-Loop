#!/usr/bin/env bash
# witness.sh — the CLAIM side of a liveness witness.
#
# Appends ONE host-stamped claim per interval, and does nothing else. It does not
# read ps and does not decide whether it is alive. Liveness is the reader's job
# (witness_reader.sh): "is there a claim newer than N intervals?" No claim -> dead,
# by definition, whatever any process table says. Death is visible as absence.
#
#   WITNESS tick=<seq> t=<host epoch> pid=<pid> interval=<seconds>
#
# The interval is IN the entry so the reader never has to infer a rhythm.
# A TOMBSTONE line is written on exit, so a death is both a gap and a marker.
#
# Start detached:  setsid nohup bash ~/kit/witness/witness.sh >/dev/null 2>&1 &
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SLAB="${SLAB:-$DIR/slab.log}"
INTERVAL="${INTERVAL:-900}"   # 15 min: quiet enough not to be noise, short enough to matter

echo $$ > "$DIR/.witness.pid"
echo "$(date -u +%FT%TZ)  up (pid $$)" >> "$DIR/.witness.log"
trap 'echo "TOMBSTONE t=$(date -u +%s) pid=$$ reason=exit" >> "$SLAB"' EXIT
seq=0
while true; do
  seq=$((seq+1))
  printf 'WITNESS tick=%s t=%s pid=%s interval=%s\n' "$seq" "$(date -u +%s)" "$$" "$INTERVAL" >> "$SLAB"
  sleep "$INTERVAL"
done
