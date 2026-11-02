#!/usr/bin/env bash
# beat_loop.sh — the Room's heartbeat: runs beat.py on an interval (default 5 min).
# A beat is a breath, not a spasm; decay is measured in hours, so this needn't be fast.
# Start detached:  setsid nohup bash ~/kit/room/beat_loop.sh >/dev/null 2>&1 &
cd "$(dirname "$0")" || exit 1
echo $$ > .beat_loop.pid
echo "$(date -u +%FT%TZ)  up (pid $$)" >> .beat_loop.log
while true; do
  python3 beat.py >> beat.log 2>&1
  date +%s > .beat_loop.beat
  sleep "${INTERVAL:-300}"
done
