#!/bin/bash
# gate check — heartbeat age + death windows (gaps > 15s) in the retained log.
HERE="$(cd "$(dirname "$0")" && pwd)"
LOG="$HERE/heartbeat.log"
now=$(date -u +%s)
[ -f "$LOG" ] || { echo "no heartbeat log — instrument not running: setsid nohup bash $HERE/heartbeat.sh >/dev/null 2>&1 &"; exit 1; }
last=$(tail -n 1 "$LOG" | awk '{print $1}')
age=$((now - last))
echo "now=$now last_beat=$last age=${age}s"
if [ "$age" -gt 15 ]; then
  echo "HEARTBEAT DEAD — restart: setsid nohup bash $HERE/heartbeat.sh >/dev/null 2>&1 &"
else
  echo "HEARTBEAT ALIVE"
fi
echo "--- death windows (gaps > 15s) in retained window ---"
if [ "$(wc -l < "$LOG")" -lt 2 ]; then
  echo "(insufficient beats)"
else
  awk 'NR>1 && $1-prev>15 {print $1-prev, prev, $1} {prev=$1}' "$LOG" | while read -r gap from to; do
    echo "gap ${gap}s  $(date -u -d "@$from" +%H:%M:%S) -> $(date -u -d "@$to" +%H:%M:%S) UTC"
  done
fi
echo "--- beats retained: $(wc -l < "$LOG") ---"
[ "$age" -le 15 ]
