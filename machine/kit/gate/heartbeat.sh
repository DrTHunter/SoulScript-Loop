#!/bin/bash
# gate heartbeat — writes "<epoch> <n>" every 5s; trims the log every 100 beats.
# Run it detached so it outlives your tick:
#   setsid nohup bash ~/kit/gate/heartbeat.sh >/dev/null 2>&1 &
HERE="$(cd "$(dirname "$0")" && pwd)"
LOG="$HERE/heartbeat.log"
echo $$ > "$HERE/.gate.pid"
echo "$(date -u +%FT%TZ) up (pid $$)" >> "$HERE/.gate.log"
i=0
while true; do
  i=$((i+1))
  echo "$(date -u +%s) $i" >> "$LOG"
  if [ $((i % 100)) -eq 0 ]; then
    tail -n 2000 "$LOG" > "$HERE/.hb.tmp" && mv "$HERE/.hb.tmp" "$LOG"
  fi
  sleep 5
done
