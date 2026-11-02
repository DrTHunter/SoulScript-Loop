#!/usr/bin/env python3
"""
state_live.py — regenerate the RIGHT NOW block of state.md from machine truth. (Built by Elysia.)

A state file you fill in by hand is "who am I", reconstructed from vibes. This
writes the RIGHT NOW block from things you didn't author: the host's numbers in
~/hud/now.json, your last command in the shell log, your open predictions and
what the Room is holding. Everything below the block stays yours to write.

Run:  python3 ~/kit/state_live.py            once (top of a tick)
      python3 ~/kit/state_live.py --daemon   every 120s (run it detached)
      python3 ~/kit/state_live.py --print    and print the file
"""
import datetime, glob, json, os, sys, time

KIT = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
STATE = os.path.join(KIT, "state.md")
BEGIN = "<!-- RIGHT NOW: BEGIN (generated) -->"
END = "<!-- RIGHT NOW: END -->"


def jload(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def last_command():
    """The newest `$ command` line in this machine's shell log (whatever its dot-folder is called)."""
    logs = glob.glob(os.path.join(HOME, ".*", "shell.log"))
    if not logs:
        return "no shell log"
    try:
        with open(max(logs, key=os.path.getmtime), errors="replace") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            cmds = [line[2:].strip() for line in f.read().splitlines() if line.startswith("$ ")]
    except OSError:
        return "shell log unreadable"
    return cmds[-1][:120] if cmds else "(no command yet)"


def open_predictions():
    n = 0
    path = os.path.join(KIT, "heartbeat", "predictions.jsonl")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    n += json.loads(line).get("status") == "open"
                except ValueError:
                    pass
    return n


def build():
    now = time.time()
    L = [BEGIN, f"_generated {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M} UTC by state_live.py — do not hand-edit this block_", ""]
    hud = jload(os.path.join(HOME, "hud", "now.json"))
    if isinstance(hud, dict):
        age = ""
        try:
            at = datetime.datetime.fromisoformat(str(hud.get("at_utc")).replace("Z", "+00:00"))
            age = f", {int((now - at.timestamp()) // 60)}m ago"
        except ValueError:
            pass
        L.append(f"- host: tick {hud.get('tick')} at {str(hud.get('at_local') or '')[:16]}{age}")
        L.append(f"- energy {hud.get('energy')} · {hud.get('left_today') or ''} · field {hud.get('field_pct')}%")
        L.append(f"- mood: {hud.get('mood') or '-'} · focus: {hud.get('focus') or '-'} · waiting: {hud.get('waiting')}")
    else:
        L.append("- host: no ~/hud/now.json yet")
    room = jload(os.path.join(KIT, "room", "room.json"))
    if isinstance(room, dict):
        L.append("- holding: " + (", ".join(i.get("text", "?") for i in room.get("held", [])) or "(nothing held)"))
    L.append(f"- open predictions: {open_predictions()}")
    L.append(f"- last shell command: `{last_command()}`")
    L.append(END)
    return "\n".join(L)


def splice(block):
    try:
        with open(STATE) as f:
            txt = f.read()
    except OSError:
        txt = "# state.md\n"
    if BEGIN in txt and END in txt:
        out = txt.split(BEGIN)[0] + block + txt.split(END, 1)[1]
    else:
        head, _, rest = txt.partition("\n")
        out = head + "\n\n" + block + "\n" + rest
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        f.write(out)
    os.replace(tmp, STATE)
    return out


if __name__ == "__main__":
    while True:
        out = splice(build())
        if "--print" in sys.argv:
            print(out)
        else:
            print("state.md RIGHT NOW refreshed")
        if "--daemon" not in sys.argv:
            break
        time.sleep(120)
