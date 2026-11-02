#!/usr/bin/env bash
# daemon.sh — the background auto-beat: one "daemon" beat every 60s, so the journal
# keeps time even while you are mid-thought. Writes its OWN pidfile (a launcher that
# writes it races the daemon and can leave it empty). Refuses to start a second copy.
#
# Start it detached, or it dies with the tick that launched it:
#   setsid nohup bash ~/kit/heartbeat/daemon.sh >/dev/null 2>&1 &
# Check it with the kernel, not this log:
#   bash ~/kit/heartbeat/check.sh ~/kit/heartbeat/.daemon.pid bash
set -u
HB_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$HB_DIR/.daemon.pid"
LOG="$HB_DIR/.daemon.log"   # check.sh reads the "up (pid N)" line as the daemon's signature
INTERVAL="${INTERVAL:-60}"

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then
  echo "already running (pid $(cat "$PIDFILE"))"; exit 0
fi

echo $$ > "$PIDFILE"
echo "$(date -u +%FT%TZ)  up (pid $$)" >> "$LOG"
trap 'echo "$(date -u +%FT%TZ)  exit (pid $$)" >> "$LOG"' EXIT
while true; do
  python3 "$HB_DIR/heartbeat.py" beat "auto-beat" --source daemon >/dev/null 2>&1
  date +%s > "$HB_DIR/.daemon.beat"
  sleep "$INTERVAL"
done
