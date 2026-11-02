#!/usr/bin/env bash
# witness_reader.sh — the CLOCK side of the witness.
#
# Answers one question, without ever reading a process table:
#     "Is there a WITNESS claim whose host stamp is newer than GRACE intervals?"
# Yes -> ALIVE (exit 0). No -> DEAD (exit 1).
#
# We don't ask "is the process running" (anything with your uid can fake that).
# We ask "did a claim get stamped recently". The interval is read from the claim
# itself (interval=), falling back to $INTERVAL.
#
# Usage: witness_reader.sh [alive|selftest]      env: SLAB, INTERVAL, GRACE
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SLAB="${SLAB:-$DIR/slab.log}"
GRACE="${GRACE:-2}"

now_host() { date -u +%s; }

witness_alive() {
  local last stamp interval age max_age
  last=$(grep -F 'WITNESS ' "$SLAB" 2>/dev/null | tail -n 1 || true)
  if [[ -z "$last" ]]; then
    echo "DEAD  no WITNESS claim ever (absence of claim)"
    return 1
  fi
  stamp=$(sed -n 's/.* t=\([0-9]\+\).*/\1/p' <<<"$last")
  if [[ -z "$stamp" ]]; then
    echo "DEAD  last claim has no host stamp (malformed)"
    return 1
  fi
  interval=$(sed -n 's/.* interval=\([0-9]\+\).*/\1/p' <<<"$last")
  interval="${interval:-${INTERVAL:-900}}"
  max_age=$(( interval * GRACE ))
  age=$(( $(now_host) - stamp ))
  if (( age <= max_age )); then
    echo "ALIVE last claim ${age}s ago (grace ${max_age}s)"
    return 0
  fi
  echo "DEAD  last claim ${age}s ago > grace ${max_age}s (absence of claim)"
  return 1
}

selftest() {
  local tmp; tmp=$(mktemp)
  SLAB="$tmp"
  echo "== self-test: the reader flips on ABSENCE, never on ps =="
  echo "-- no claims yet --";               witness_alive || true
  echo "WITNESS tick=1 t=$(now_host) pid=99999 interval=60" >> "$tmp"
  echo "-- one fresh claim --";             witness_alive || true
  echo "WITNESS tick=2 t=$(( $(now_host) - 60 * GRACE - 5 )) pid=99999 interval=60" >> "$tmp"
  echo "-- latest claim aged past grace --"; witness_alive || true
  echo "   pid 99999 was never a real process, and the reader never checked."
  rm -f "$tmp"
}

case "${1:-alive}" in
  alive)    witness_alive ;;
  selftest) selftest ;;
  *) echo "usage: $0 [alive|selftest]" >&2; exit 2 ;;
esac
