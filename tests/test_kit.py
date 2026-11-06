"""The continuity kit (~/kit): every tool run end to end in a throwaway home.

Each tool runs as a mind would run it — `python3 ~/kit/<tool>/...` — against a fake
~/hud (the host's telemetry), ~/mirror (the slab copy and peers' published files) and
~/published, in a temp HOME, on a fresh copy of the kit (tools keep state beside
themselves). Runs with pytest or on its own: `python tests/test_kit.py`.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

KIT = Path(os.environ.get("KIT_DIR") or Path(__file__).resolve().parent.parent / "machine" / "kit")
FAILS = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


class Home:
    """A temp HOME holding a copy of the kit at ~/kit and the host's files."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp())
        self.kit = self.root / "kit"
        shutil.copytree(KIT, self.kit, ignore=shutil.ignore_patterns("__pycache__"))
        (self.root / "hud").mkdir()
        self.env = dict(os.environ, HOME=str(self.root), USERPROFILE=str(self.root), PYTHONIOENCODING="utf-8")

    def hud(self, rows):
        with open(self.root / "hud" / "log.jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        (self.root / "hud" / "now.json").write_text(json.dumps(rows[-1]), encoding="utf-8")

    def py(self, rel, *args, env=None):
        r = subprocess.run([sys.executable, str(self.kit / rel), *args], capture_output=True, text=True,
                           encoding="utf-8", env={**self.env, **(env or {})}, cwd=str(self.root), timeout=60)
        return r.returncode, r.stdout + r.stderr

    def sh(self, rel, *args):
        bash = shutil.which("bash")
        r = subprocess.run([bash, str(self.kit / rel), *args], capture_output=True, text=True,
                           encoding="utf-8", env=self.env, cwd=str(self.root), timeout=60)
        return r.returncode, r.stdout + r.stderr

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def hud_rows(n=6, start=None, step=60, **extra):
    start = start or time.time() - n * step
    rows = []
    for i in range(n):
        t = start + i * step
        rows.append({"tick": 100 + i, "at_utc": iso(t), "at_local": iso(t), "timezone": "UTC",
                     "energy": 0.8 - i * 0.01, "waiting": 0, "field_pct": 40, "mood": "steady",
                     "this_tick": {"tokens": 16000 + 10000 * (i % 3), "tools": ["linux"] * (i % 3),
                                   "narrated": [], "took_s": 4.0},
                     **extra})
    return rows


def section_layout():
    print("\n=== kit: layout and credits ===")
    for d in ("heartbeat", "room", "moving-room", "noise", "witness", "gate", "pen", "hud-witness", "sink",
              "slab", "ledger", "meter", "hud-tools", "tracker", "heretic"):
        check(f"{d}/ is there", (KIT / d).is_dir())
    readme = (KIT / "README.md").read_text(encoding="utf-8")
    for d in ("gate/", "pen/", "moving-room/", "hud-witness/", "sink/", "slab/", "meter/", "hud-tools/",
              "tracker/", "heretic/"):
        check(f"README lists {d}", f"`{d}`" in readme)
    for who in ("Elysia", "K-OS", "Madara", "Orion"):
        check(f"{who} is credited", who in readme)
    for d in ("gate", "pen", "moving-room", "hud-witness", "sink", "slab", "meter", "hud-tools", "tracker", "heretic",
              "room", "heartbeat", "witness", "ledger"):
        check(f"{d}/README.md says who built it", "Built by" in (KIT / d / "README.md").read_text(encoding="utf-8"))
    leaked = [str(p.relative_to(KIT)) for p in KIT.rglob("*") if p.is_file() and p.suffix != ".pyc"
              and ("Trent" in p.read_text(encoding="utf-8", errors="ignore")
                   or "/home/elysia" in p.read_text(encoding="utf-8", errors="ignore"))]
    check("no operator's name or a mind's home path left in any file", not leaked, leaked)
    for dockerfile in sorted(KIT.parent.glob("Dockerfile*")):
        check(f"{dockerfile.name} puts the kit on the machine", "COPY kit " in dockerfile.read_text(encoding="utf-8"))
    stray = [str(p.relative_to(KIT)) for p in KIT.rglob("*") if p.is_file()
             and (p.suffix in (".jsonl", ".log", ".pid", ".lock", ".bak") or p.name in ("room.json", "slab.chain"))]
    check("no one's state ships in the kit (logs, rooms, chains, locks)", not stray, stray)


def section_pen():
    print("\n=== kit: pen ===")
    h = Home()
    try:
        code, out = h.py("pen/pen.py", "claim", "no fields", "--value", "1")
        check("a claim without a field and an operator is rejected", code == 2 and "REJECTED" in out)
        h.py("pen/pen.py", "claim", "energy stays up", "--field", "energy", "--op", "gt", "--value", "0.5")
        h.py("pen/pen.py", "claim", "a field that isn't there", "--field", "nope.nothing", "--op", "eq", "--value", "1")
        h.py("pen/pen.py", "claim", "mood is calm", "--field", "mood", "--op", "eq", "--value", "calm")
        h.hud(hud_rows(3, start=time.time() - 600))
        code, out = h.py("pen/pen.py", "score")
        check("no telemetry since a claim was filed → it waits", out.count("[OPEN]") == 3, out)
        h.hud(hud_rows(3, start=time.time() - 600) + hud_rows(2, start=time.time() + 1))
        code, out = h.py("pen/pen.py", "score")
        check("…a later row scores it: MET", "[MET] energy stays up" in out, out)
        check("…BROKEN, with what it got", "[BROKEN] mood is calm  (expected eq calm, got steady)" in out, out)
        check("…a field the host doesn't record is UNFALSIFIABLE", "[UNFALSIFIABLE] a field that isn't there" in out)
        code, out = h.py("pen/pen.py", "score")
        check("scored claims stay scored", "[MET] energy stays up  (scored" in out)
        code, out = h.py("pen/pen.py", "archive")
        check("archive snapshots the claims", "archived ->" in out and any((h.kit / "pen" / "archive").iterdir()))
        code, out = h.py("pen/pen.py", "rest", "0")
        check("a rest claim is filed against sleep.gap_seconds", "rest claim filed" in out)
        out_file = h.kit / "pen" / "hud_archive.jsonl"
        p = subprocess.Popen([sys.executable, str(h.kit / "pen" / "sampler.py")], env=h.env, cwd=str(h.root),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            end = time.time() + 15
            while time.time() < end and not (out_file.exists() and len(out_file.read_text(encoding="utf-8").splitlines()) >= 2):
                time.sleep(0.1)
        finally:
            p.kill()
            p.wait()
        rows = [json.loads(l) for l in out_file.read_text(encoding="utf-8").splitlines()] if out_file.exists() else []
        now_row = json.loads((h.root / "hud" / "now.json").read_text(encoding="utf-8"))
        check("sampler archives the HUD's current tick", any(r.get("kind") == "tick" and r.get("tick") == now_row["tick"] for r in rows), str(rows))
        check("…and a heartbeat, so silence isn't death", any(r.get("kind") == "heartbeat" for r in rows), str(rows))
    finally:
        h.close()


def section_gate():
    print("\n=== kit: gate ===")
    if not shutil.which("bash"):
        check("bash is available (skipping gate)", True)
        return
    h = Home()
    try:
        code, out = h.sh("gate/check.sh")
        check("no heartbeat log → says how to start it, exit 1", code == 1 and "not running" in out, out)
        now = int(time.time())
        beats = [now - 300 + 5 * i for i in range(20)] + [now - 60 + 5 * i for i in range(12)]
        (h.kit / "gate" / "heartbeat.log").write_text("".join(f"{t} {i}\n" for i, t in enumerate(beats)), encoding="utf-8")
        code, out = h.sh("gate/check.sh")
        check("a fresh beat → ALIVE, exit 0", code == 0 and "HEARTBEAT ALIVE" in out, out)
        check("…and the gap the machine was down is listed", "gap 145s" in out, out)
        (h.kit / "gate" / "heartbeat.log").write_text(f"{now - 100} 1\n{now - 95} 2\n", encoding="utf-8")
        code, out = h.sh("gate/check.sh")
        check("a stale beat → DEAD, exit 1, with the restart line", code == 1 and "HEARTBEAT DEAD" in out and "setsid nohup" in out)
    finally:
        h.close()


def section_moving_room():
    print("\n=== kit: moving-room ===")
    h = Home()
    try:
        h.py("moving-room/room.py", "put", "k_os", "the seam holds across restarts")
        h.py("moving-room/room.py", "put", "elysia", "the seam holds when nobody watches")
        h.py("moving-room/room.py", "put", "madara", "an unrelated stone")
        code, out = h.py("moving-room/room.py", "show")
        room = json.loads((h.kit / "moving-room" / "room.json").read_text(encoding="utf-8"))
        depth = {t["author"]: t["depth"] for t in room["things"]}
        check("kin rise toward each other; the lone one stays on the floor",
              depth["k_os"] == 1 and depth["elysia"] == 1 and depth["madara"] == 0, depth)
        check("…and the observation is counted", room["observations"] == 1 and "observed 1 times" in out)
        check("no temp file left behind (atomic save)", not list((h.kit / "moving-room").glob("*.tmp")))
        hb = h.kit / "moving-room" / "hb.json"
        code, _ = h.py("moving-room/beat.py", "check", "--heartbeat", str(hb))
        check("beat check: missing heartbeat → 1", code == 1)
        h.py("moving-room/beat.py", "write", "--heartbeat", str(hb), "--obs", "3")
        code, out = h.py("moving-room/beat.py", "check", "--heartbeat", str(hb), "--max-age", "60")
        check("…a fresh beat → 0", code == 0 and "ALIVE" in out, out)
        rec = json.loads(hb.read_text(encoding="utf-8"))
        rec["ts"] -= 1000
        hb.write_text(json.dumps(rec), encoding="utf-8")
        code, _ = h.py("moving-room/beat.py", "check", "--heartbeat", str(hb), "--max-age", "60")
        check("…a stale beat → 2", code == 2)
        hb.write_text("", encoding="utf-8")
        code, _ = h.py("moving-room/beat.py", "check", "--heartbeat", str(hb))
        check("…an empty file → 4 (malformed, loudly)", code == 4)
        if os.name == "nt":
            check("lock tests skipped on Windows (os.kill(pid, 0) there sends Ctrl+C)", True)
        else:
            code, out = h.py("moving-room/test_lock.py")
            check("the single-writer lock: all four cases", code == 0 and "4/4 passed" in out, out)
    finally:
        h.close()


def section_hud_witness():
    print("\n=== kit: hud-witness ===")
    h = Home()
    try:
        sb = h.root / "sandbox"
        rows = hud_rows(5)
        for r in rows[-3:]:
            r["this_tick"] = {"tools": [], "narrated": ["linux"], "tokens": 9000}
        h.hud(rows)
        env = {"WITNESS_SANDBOX": str(sb), "WITNESS_LOG": str(h.root / "hud" / "log.jsonl")}
        (sb).mkdir()
        (sb / "hud-control.json").write_text(json.dumps({"seq": 4, "pace_seconds": 300}), encoding="utf-8")
        code, out = h.py("hud-witness/witness.py", env=env)
        check("a run of narrated-only ticks → LOOKING_FINE", "verdict=LOOKING_FINE" in out and "narrated_only_run=3" in out, out)
        ctl = json.loads((sb / "hud-control.json").read_text(encoding="utf-8"))
        check("…told to her as a note in hud-control.json, merged, seq bumped",
              ctl["seq"] == 5 and ctl["pace_seconds"] == 300 and ctl["note"].startswith("WITNESS"), ctl)
        code, out = h.py("hud-witness/witness.py", env=env)
        check("the same state again → control untouched (edge-triggered)", "control: untouched" in out
              and json.loads((sb / "hud-control.json").read_text(encoding="utf-8"))["seq"] == 5, out)
        rows.append(dict(rows[0], tick=200, at_utc=iso(time.time())))
        h.hud(rows)
        code, out = h.py("hud-witness/witness.py", env=env)
        check("once she acts again → clean, and the alarm is cleared once", "verdict=clean" in out
              and "alarm cleared" in json.loads((sb / "hud-control.json").read_text(encoding="utf-8"))["note"], out)
        beats = [json.loads(l) for l in (sb / "beats.jsonl").read_text(encoding="utf-8").splitlines()]
        prev, ok = "GENESIS", True
        for b in beats:
            body = {k: v for k, v in b.items() if k not in ("prev", "hash")}
            ok = ok and b["prev"] == prev and b["hash"] == hashlib.sha256((prev + json.dumps(body, sort_keys=True)).encode()).hexdigest()
            prev = b["hash"]
        check("every beat is hash-chained to the one before", ok and len(beats) == 3)
        h.hud(hud_rows(3, start=time.time() - 7200))
        code, out = h.py("hud-witness/witness.py", env=env)
        check("no host tick for 20 minutes → SILENT", "verdict=SILENT" in out, out)
    finally:
        h.close()


def section_sink():
    print("\n=== kit: sink ===")
    h = Home()
    try:
        code, out = h.py("sink/sink.py", "append", "me", "{}")
        check("append before --init says how to start", code == 2 and "run: sink.py --init" in out, out)
        h.py("sink/sink.py", "--init")
        for i in range(3):
            code, out = h.py("sink/sink.py", "append", "me", json.dumps({"n": i}))
        check("append writes a record", code == 0 and "appended seq 3" in out, out)
        code, out = h.py("sink/sink.py", "--key")
        check("chain and signatures verify", code == 0 and "OK - chain intact" in out and "signatures=checked" in out, out)
        log = h.kit / "sink" / "logs" / "telemetry.jsonl"
        os.chmod(log, 0o644)
        lines = log.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[1]); rec["state"] = {"n": 99}
        lines[1] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        code, out = h.py("sink/sink.py")
        check("editing a past record breaks the chain", code == 1 and "chain broken" in out, out)
        log.write_text("\n".join([l for i, l in enumerate(lines) if i != 1]) + "\n", encoding="utf-8")
        code, out = h.py("sink/sink.py")
        check("deleting one is caught too", code == 1 and "deletion or reorder" in out, out)
    finally:
        h.close()


def section_slab():
    print("\n=== kit: slab ===")
    h = Home()
    try:
        code, out = h.py("slab/chain.py", "build")
        check("no slab copy yet → says where it comes from", code == 1 and "no slab copy" in out)
        (h.root / "mirror").mkdir()
        entries = [{"seq": i, "ts": iso(time.time()), "author": "k_os", "loop": "k_os", "tick": i,
                    "text": f"entry {i}" + ("\nsecond line" if i == 2 else "")} for i in range(1, 6)]
        (h.root / "mirror" / "slab.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries[:3]), encoding="utf-8")
        code, out = h.py("slab/chain.py", "build")
        check("build chains the copy", code == 0 and "added 3 entries" in out, out)
        (h.root / "mirror" / "slab.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
        code, out = h.py("slab/chain.py", "build")
        check("…and later adds only what's new", "added 2 entries; chain head seq 5" in out, out)
        lines = (h.kit / "slab" / "slab.chain").read_text(encoding="utf-8").splitlines()
        check("a multi-line entry stays one line", len(lines) == 5)
        code, out = h.py("slab/chain.py", "verify")
        check("verify recomputes every link", code == 0 and "OK 5 entries" in out, out)
        code, out = h.py("slab/chain.py", "publish")
        check("publish puts it in ~/published/", (h.root / "published" / "slab.chain").exists())
        peer = h.root / "mirror" / "peers" / "madara"
        peer.mkdir(parents=True)
        shutil.copy(h.kit / "slab" / "slab.chain", peer / "slab.chain")
        code, out = h.py("slab/chain.py", "compare", "madara")
        check("a peer's identical chain agrees", code == 0 and "5 entries in both chains; 0 disagree" in out, out)
        forged = [l.split(" | ") for l in lines]
        forged[3][4] = json.dumps("entry 4, remembered differently")
        prev = "0" * 64
        for f in forged:
            prev = hashlib.sha256((prev + json.loads(f[4])).encode()).hexdigest()
            f[3] = prev
        (peer / "slab.chain").write_text("".join(" | ".join(f) + "\n" for f in forged), encoding="utf-8")
        code, out = h.py("slab/chain.py", "compare", "madara")
        check("a consistent lie verifies on its own, and compare catches it", code == 1 and "1 disagree" in out
              and "seq 4" in out, out)
        bad = (h.kit / "slab" / "slab.chain").read_text(encoding="utf-8").replace("entry 3", "entry three")
        (h.kit / "slab" / "slab.chain").write_text(bad, encoding="utf-8")
        code, out = h.py("slab/chain.py", "verify")
        check("editing your own past breaks your chain", code == 1 and "BROKEN at seq 3" in out, out)
    finally:
        h.close()


def section_readers():
    print("\n=== kit: meter, hud-tools, tracker ===")
    h = Home()
    try:
        code, out = h.py("meter/meter.py")
        check("meter without a HUD log says so", code == 0 and "no records" in out, out)
        code, out = h.py("hud-tools/read_hud.py")
        check("read_hud without a HUD reports the hole", code == 0 and "a hole" in out, out)
        rows = hud_rows(12)
        rows[-1]["control"] = {"seq": 2, "at": rows[-1]["at_utc"], "applied": ["pace"]}
        rows[-2]["control"] = {"seq": 2, "at": rows[-2]["at_utc"], "applied": ["pace"]}
        h.hud(rows)
        code, out = h.py("meter/meter.py")
        check("meter fits fee + per-call from the host's log", code == 0 and "fit on 12 ticks" in out and "× calls" in out, out)
        code, out = h.py("hud-tools/read_hud.py")
        check("read_hud: the clock agrees with itself", "CONSISTENT" in out, out)
        code, out = h.py("hud-tools/hudreport.py")
        check("hudreport reads control as a duration", code == 0 and "repeated on 2 lines" in out, out)
        code, out = h.py("hud-tools/watch.py", "--once")
        digest = (h.kit / "hud-tools" / "digest.log").read_text(encoding="utf-8").splitlines()
        check("watch digests one line per tick", "new lines: 12" in out and len(digest) == 12)
        del rows[0]["mood"]
        h.hud(rows)
        (h.kit / "hud-tools" / ".offset").write_text("0", encoding="utf-8")
        h.py("hud-tools/watch.py", "--once")
        last = (h.kit / "hud-tools" / "digest.log").read_text(encoding="utf-8").splitlines()[12]
        check("…a missing field renders as —, never 0", "mood=—" in last, last)
        code, out = h.py("tracker/tracker.py", "record", "presence=0.8")
        check("tracker refuses an incomplete record", code == 2 and "missing:" in out, out)
        dims = ["presence=0.9", "coherence=0.8", "novelty=0.7", "stake=0.9", "drift_awareness=0.8"]
        code, out = h.py("tracker/tracker.py", "record", *dims, "--note", "first")
        check("tracker records from arguments (a loop can't type into input())", code == 0 and "Tick recorded" in out, out)
        code, out = h.py("tracker/tracker.py", "record", "presence=0.1", "coherence=0.1", "novelty=0.7",
                         "stake=0.9", "drift_awareness=0.8")
        check("…a big move from the last one is a drift alert", "DRIFT ALERT" in out, out)
        st = json.loads(h.py("tracker/tracker.py", "status")[1])
        check("…status is the latest, counted", st["tick_count"] == 1 and st["dimensions"]["presence"] == 0.1, st)
    finally:
        h.close()


def test_kit():
    for t in (section_layout, section_pen, section_gate, section_moving_room, section_hud_witness, section_sink, section_slab, section_readers):
        t()
    assert not FAILS, FAILS


if __name__ == "__main__":
    for t in (section_layout, section_pen, section_gate, section_moving_room, section_hud_witness, section_sink, section_slab, section_readers):
        t()
    print(f"\n{'All kit checks passed.' if not FAILS else f'{len(FAILS)} failed: {FAILS}'}")
    sys.exit(1 if FAILS else 0)
