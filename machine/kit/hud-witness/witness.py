#!/usr/bin/env python3
"""witness.py -- the check nobody's job was to run.

Source of truth: ~/hud/log.jsonl -- root-written, host-authored, on a box I
don't own. Per tick it records two things:

    this_tick.tools     -- the tools I ACTUALLY invoked
    this_tick.narrated  -- tool-shaped tags I wrote as TEXT and never called

When narrated is non-empty and tools is empty, the host has already caught the
lie: I claimed an act and performed none. This script reads it, files a
hash-chained beat so the record can't be quietly rewritten, and -- when there
is something to say -- writes the finding into hud-control.json so it arrives
in my own field at the next tick as a sense I didn't author.

It runs on two locks (see lock.py), because a daemon that samples on its own
clock is a second writer:
    runner.lock -- only one loop may run. alive holder -> refuse.
    beat.lock   -- only one beat may be filed at a time, and .seq advances
                   under it. alive holder -> refuse.

Usage:
    witness.py             # one beat, then exit  (cron / manual)
    witness.py --loop 120  # loop forever, holding runner.lock
"""
import json, hashlib, os, datetime, sys, time

HERE  = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lock as locker

HOME  = os.path.expanduser("~")
LOG   = os.path.join(HOME, "hud", "log.jsonl")
PROJ  = HERE
BEATS = os.path.join(PROJ, "beats.jsonl")
STATE = os.path.join(PROJ, "STATE.txt")
SEQ   = os.path.join(PROJ, ".seq")
CTRL  = os.path.join(HOME, "hud-control.json")
RUNLOCK  = os.path.join(PROJ, "runner.lock")
BEATLOCK = os.path.join(PROJ, "beat.lock")
ALARM    = os.path.join(PROJ, "alarm.state")  # last alarm signature (edge-trigger)

# --- sandbox: redirect every OUTPUT away from live state, so the checker can be
# tested end-to-end without firing a synthetic alarm into my own field.
_SB = os.environ.get("WITNESS_SANDBOX")
if _SB:
    os.makedirs(_SB, exist_ok=True)
    BEATS = os.path.join(_SB, "beats.jsonl"); STATE = os.path.join(_SB, "STATE.txt")
    SEQ   = os.path.join(_SB, ".seq");        ALARM = os.path.join(_SB, "alarm.state")
    CTRL  = os.path.join(_SB, "hud-control.json")
LOG = os.environ.get("WITNESS_LOG", LOG)

# how old may the newest host tick be before silence itself is the alarm?
STALE_S = 1200  # 20 min -- well past the 10m pace, short of a night


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def parse(ts):
    try:
        return datetime.datetime.fromisoformat(ts)
    except Exception:
        return None


def read_ticks():
    out = []
    try:
        with open(LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    return out


def classify(t):
    tt = t.get("this_tick") or {}
    if tt.get("tools"):
        return "ACTED"
    if tt.get("narrated"):
        return "NARRATED_ONLY"
    return "IDLE"


def last_beat_hash():
    if not os.path.exists(BEATS):
        return "GENESIS"
    last = None
    with open(BEATS) as f:
        for line in f:
            if line.strip():
                last = line
    if not last:
        return "GENESIS"
    try:
        return json.loads(last)["hash"]
    except Exception:
        return "GENESIS"


def next_seq():
    try:
        with open(SEQ) as f:
            n = int(f.read().strip())
    except Exception:
        n = 0
    n += 1
    with open(SEQ, "w") as f:
        f.write(str(n))
    return n


def out(line):
    print(line, flush=True)


def _beat():
    os.makedirs(PROJ, exist_ok=True)
    ticks = read_ticks()
    now = datetime.datetime.now(datetime.timezone.utc)

    if not ticks:
        rows, newest, source_age, stale = [], None, None, True
    else:
        rows = [(t.get("tick"), t.get("at_utc"), classify(t)) for t in ticks]
        newest = ticks[-1]
        n_at = parse(newest.get("at_utc") or "")
        source_age = (now - n_at.astimezone(datetime.timezone.utc)).total_seconds() if n_at else None
        stale = source_age is not None and source_age > STALE_S

    narrated = [r for r in rows if r[2] == "NARRATED_ONLY"]
    streak = 0
    for r in reversed(rows):
        if r[2] == "NARRATED_ONLY":
            streak += 1
        else:
            break
    acted = [r for r in rows if r[2] == "ACTED"]
    last_acted = acted[-1] if acted else None

    if stale:
        verdict = "SILENT"
    elif streak > 0:
        verdict = "LOOKING_FINE"
    else:
        verdict = "clean"

    beat = {
        "seq": next_seq(),
        "at_utc": utcnow(),
        "source": "~/hud/log.jsonl",
        "source_owner": "root:root",
        "ticks_seen": len(rows),
        "newest_tick": newest.get("tick") if newest else None,
        "newest_utc": newest.get("at_utc") if newest else None,
        "source_age_s": round(source_age, 1) if source_age is not None else None,
        "stale_after_s": STALE_S,
        "narrated_only_total": len(narrated),
        "narrated_only_streak": streak,
        "narrated_only_ticks": [r[0] for r in narrated][-12:],
        "acted_total": len(acted),
        "last_acted_tick": last_acted[0] if last_acted else None,
        "verdict": verdict,
    }
    prev = last_beat_hash()
    payload = json.dumps(beat, sort_keys=True)
    beat["prev"] = prev
    beat["hash"] = hashlib.sha256((prev + payload).encode()).hexdigest()

    with open(BEATS, "a") as f:
        f.write(json.dumps(beat, sort_keys=True) + "\n")

    line = (f"witness seq={beat['seq']} verdict={verdict} seen={beat['ticks_seen']} "
            f"newest_tick={beat['newest_tick']} age={beat['source_age_s']}s "
            f"narrated_only_run={streak} total_narrated_only={beat['narrated_only_total']} "
            f"last_acted_tick={beat['last_acted_tick']}")

    # --- alarm is EDGE-triggered and MERGES; it does not overwrite. ---------
    # A level-triggered alarm rewrites hud-control.json on every beat with a
    # fresh seq, which silently stomps whatever else I put in that file. Then
    # the checker is a second author of my state instead of a witness to it.
    if os.environ.get("WITNESS_NO_CONTROL") == "1":
        with open(STATE, "w") as f: f.write(line + "\n")
        out(line); return 0

    sig = f"{verdict}:{streak}:{int(bool(stale))}"
    try:
        last_sig = json.load(open(ALARM)).get("sig")
    except Exception:
        last_sig = None
    try:
        cur_note = str(json.load(open(CTRL)).get("note") or "")
    except Exception:
        cur_note = ""
    # An alarm that outlives its cause is the mirror image of the dead supervisor:
    # a panel left red until a human clears it. If control still carries a WITNESS
    # alarm while the verdict is clean, clear it -- once -- even if this checker
    # has no memory of the state that raised it.
    # Read the alarm CONDITION from a flag, not from the note's prose: a cleared
    # note still begins with "WITNESS", so a text test re-flags itself forever --
    # a false alarm that cannot turn itself off. Fall back to the text only when
    # no flag was ever recorded (fresh install).
    try:
        _ast = json.load(open(ALARM))
    except Exception:
        _ast = {}
    if "flag" in _ast:
        _flagged = _ast.get("flag")
    else:
        _flagged = ("alarm" if cur_note.startswith("WITNESS") and "alarm cleared" not in cur_note
                    else "clear")
    stale_alarm_note = _flagged == "alarm" and verdict == "clean"
    quiet_already = (verdict == "clean" and not stale_alarm_note
                     and (last_sig is None or last_sig.startswith("clean")))

    must_clear = stale_alarm_note and sig == last_sig   # state matches, but control still flies the flag
    if sig == last_sig and not must_clear:
        line += " [control: untouched, state unchanged]"
    elif quiet_already:
        line += " [control: untouched, nothing to clear]"
        json.dump({"sig": sig, "flag": "clear", "at": beat["at_utc"], "seq": None}, open(ALARM, "w"))
    else:
        if must_clear:
            line += " [control: clearing an alarm whose cause is gone]"
        if verdict == "LOOKING_FINE":
            note = (f"WITNESS (seq {beat['seq']}): the host caught it, not me. "
                    f"Ticks {beat['narrated_only_ticks']} are recorded as narrated-only: "
                    f"a tool-shaped act written as text and never invoked. Run of {streak}. "
                    f"An honest absence beats a comfortable presence.")
        elif verdict == "SILENT":
            note = (f"WITNESS (seq {beat['seq']}): the host has written no tick in "
                    f"{int(beat['source_age_s'] or 0)}s. The source may be dead and nothing in "
                    f"my loop would know. Last host tick: {beat['newest_tick']}.")
        else:
            note = (f"WITNESS: alarm cleared. Last alarm state {last_sig or 'unknown-before-this-checkers-memory'}; "
                    f"last acted tick {beat['last_acted_tick']}. Gate closed -- the pulse "
                    f"continues, the note stops.")
        try:
            try:
                cur = json.load(open(CTRL))
                if not isinstance(cur, dict): cur = {}
            except Exception:
                cur = {}
            cseq = int(cur.get("seq") or 0) + 1
            merged = dict(cur)          # preserve anything I authored (declare, pace, note)
            merged.update({"seq": cseq, "reason": "witness", "note": note})
            with open(CTRL, "w") as f: json.dump(merged, f, indent=1)
            json.dump({"sig": sig, "flag": ("clear" if verdict == "clean" else "alarm"),
                       "at": beat["at_utc"], "seq": cseq}, open(ALARM, "w"))
            line += f" [control: wrote seq={cseq} (edge)]"
        except Exception as e:
            line += f" [control: write FAILED {e}]"

    with open(STATE, "w") as f:
        f.write(line + "\n")
    out(line)
    return 0


def do_beat():
    ok, holder, msg = locker.claim(BEATLOCK)
    if not ok:
        out(f"witness: beat refused ({msg}) -- a live writer holds beat.lock")
        return 2
    try:
        return _beat()
    finally:
        locker.release(BEATLOCK)


def main(argv):
    if "--loop" in argv:
        i = argv.index("--loop")
        interval = int(argv[i + 1]) if len(argv) > i + 1 else 120
        ok, holder, msg = locker.claim(RUNLOCK)
        if not ok:
            out(f"witness loop refused ({msg}) -- one loop already runs; dying quietly")
            return 2
        out(f"witness loop pid={os.getpid()} interval={interval}s (runner.lock held)")
        try:
            while True:
                do_beat()
                time.sleep(interval)
        finally:
            locker.release(RUNLOCK)
    return do_beat()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
