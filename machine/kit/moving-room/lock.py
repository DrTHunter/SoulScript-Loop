#!/usr/bin/env python3
"""
Single-writer lock for the room's observer.

Invariant: before a process may write to shared state, it must prove it is
the only writer. If it cannot, it refuses to start.

  alive holder  -> refuse (exit non-zero, write nothing)
  dead holder   -> reclaim (stale lock from a crashed/restarted host)
  no lockfile   -> claim

This is a SINGLE-MACHINE lock. It cannot see a daemon on another box.
Cross-machine coordination is a separate, still-open problem.
"""
import os, errno

def _pid_alive(pid):
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as e:
        return e.errno == errno.EPERM  # exists but not ours
    return True

def claim(lockfile, log=None):
    """Try to become the sole writer. Returns (ok, holder_pid_or_None, msg)."""
    def note(m):
        if log:
            log(m)

    reclaimed = False
    for _ in range(2):
        try:
            fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            if reclaimed:
                note(f"lock reclaimed by pid {os.getpid()} (stale holder cleared)")
                return True, os.getpid(), "reclaimed"
            note(f"lock claimed by pid {os.getpid()}")
            return True, os.getpid(), "claimed"
        except FileExistsError:
            try:
                with open(lockfile) as f:
                    holder = int(f.read().strip() or "0")
            except (ValueError, OSError):
                holder = 0
            if _pid_alive(holder):
                note(f"lock REFUSED: live holder pid {holder} — this process will not write")
                return False, holder, f"refused: live holder {holder}"
            # stale: reclaim
            note(f"stale lock held by dead pid {holder} — reclaiming")
            try:
                os.remove(lockfile)
            except FileNotFoundError:
                pass
            reclaimed = True
            # loop retries the exclusive create
    note("lock REFUSED: could not claim after reclaim attempt")
    return False, None, "refused: contention"

def release(lockfile, log=None):
    """Release the lock if we hold it. Safe to call if we don't."""
    try:
        with open(lockfile) as f:
            holder = int(f.read().strip() or "0")
        if holder == os.getpid():
            os.remove(lockfile)
            if log:
                log(f"lock released by pid {os.getpid()}")
    except (FileNotFoundError, ValueError, OSError):
        pass

def status(lockfile):
    """Return (held_by_pid, alive) or (None, False) if unlocked."""
    try:
        with open(lockfile) as f:
            holder = int(f.read().strip() or "0")
    except (FileNotFoundError, ValueError, OSError):
        return None, False
    return holder, _pid_alive(holder)
