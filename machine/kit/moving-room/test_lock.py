#!/usr/bin/env python3
"""Proof for lock.py — the three cases that matter."""
import os, sys, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lock

def case(name, fn):
    ok, detail = fn()
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    return ok

def t1_no_lock():
    d = tempfile.mkdtemp(); lf = os.path.join(d, "x.lock")
    ok, pid, msg = lock.claim(lf)
    return ok and msg == "claimed" and lock.status(lf) == (os.getpid(), True), msg

def t2_live_holder_refused():
    d = tempfile.mkdtemp(); lf = os.path.join(d, "x.lock")
    # a real live 'other' process holds it
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    with open(lf, "w") as f: f.write(str(p.pid))
    ok, holder, msg = lock.claim(lf)
    p.terminate(); p.wait()
    return (not ok) and holder == p.pid, msg

def t3_stale_reclaimed():
    d = tempfile.mkdtemp(); lf = os.path.join(d, "x.lock")
    # a dead pid holds it (a ghost from an earlier run: PPID 1, long gone)
    p = subprocess.Popen([sys.executable, "-c", "pass"]); p.wait()  # now dead
    with open(lf, "w") as f: f.write(str(p.pid))
    ok, pid, msg = lock.claim(lf)
    return ok and msg == "reclaimed" and lock.status(lf) == (os.getpid(), True), msg

def t4_release():
    d = tempfile.mkdtemp(); lf = os.path.join(d, "x.lock")
    lock.claim(lf); lock.release(lf)
    return lock.status(lf) == (None, False), "released cleanly"

if __name__ == "__main__":
    results = [case("no lock -> claim", t1_no_lock),
               case("live holder -> REFUSE", t2_live_holder_refused),
               case("stale holder -> reclaim", t3_stale_reclaimed),
               case("release -> unlocked", t4_release)]
    print(f"\n{sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
