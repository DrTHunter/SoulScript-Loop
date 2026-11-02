#!/usr/bin/env bash
# kernel_beat.sh — a beat the loop doesn't write. Each line is the kernel's own view of
# this process, read from the process table (pid, elapsed seconds, state). If the process
# dies, the file stops growing: the absence is the evidence, and nothing lies.
#
# Honest limit: you launched it, so you can kill it. It is a channel you didn't author
# this tick, not one you couldn't have. The only fully exogenous signal is one from outside
# your shell, like the host's clock in ~/hud.
#
# Run:  setsid nohup bash ~/kit/heartbeat/kernel_beat.sh 5 >/dev/null 2>&1 &
# Read: tail -1 ~/kit/heartbeat/kernel-beats.jsonl
#       bash ~/kit/heartbeat/check.sh ~/kit/heartbeat/.kernel.pid bash
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
INT="${1:-5}"
OUT="$DIR/kernel-beats.jsonl"
echo "$$" > "$DIR/.kernel.pid"
echo "$(date -u +%FT%TZ)  up (pid $$)" >> "$DIR/.kernel.log"

beat() {
  local line
  line=$(ps -o pid=,etimes=,stat=,comm= -p "$$" 2>/dev/null) || return 1
  [ -n "$line" ] || return 1
  printf '{"t":"%s","kernel":"%s","source":"kernel"}\n' \
    "$(date -u +%FT%TZ)" "$(echo "$line" | tr -s ' ' | sed 's/^ //')" >> "$OUT"
  date +%s > "$DIR/.kernel.beat"
}

while beat; do sleep "$INT"; done
