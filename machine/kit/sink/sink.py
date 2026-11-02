#!/usr/bin/env python3
"""sink.py - hash-chained, HMAC-signed append-only telemetry sink.

Guarantee mechanics:
  - Every record commits to the hash of the previous one (chain link, unkeyed sha256).
  - Every record carries an HMAC over its canonical bytes (authenticity, needs writer key).
  - The log is sealed to 0444 after each append.
Integrity (chain) is checkable by anyone. Authenticity (signature) needs the key.
"""
import hashlib, hmac, json, os, secrets, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG  = ROOT / "logs" / "telemetry.jsonl"
KEY  = ROOT / "logs" / "writer.key"
GENESIS = "0" * 64

def canonical(rec: dict) -> bytes:
    body = {k: rec[k] for k in ("seq", "prev", "at_utc", "agent", "state")}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()

def link(rec: dict) -> str:
    return hashlib.sha256(canonical(rec)).hexdigest()

def sign(rec: dict, key: bytes) -> str:
    return hmac.new(key, canonical(rec) + rec["prev"].encode(), hashlib.sha256).hexdigest()

def load_key(path=KEY):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"no writer key at {path} - run: sink.py --init")
    return path.read_bytes()

def init(force=False):
    ROOT.joinpath("logs").mkdir(parents=True, exist_ok=True)
    if KEY.exists() and not force:
        print(f"key exists: {KEY} (use --force to rotate)")
    else:
        KEY.write_bytes(secrets.token_bytes(32)); os.chmod(KEY, 0o400)
        print(f"wrote writer key: {KEY} (mode 0400)")
    if LOG.exists() and not force:
        print(f"log exists: {LOG} ({len(read_raw())} records)")
        return
    LOG.write_text(""); os.chmod(LOG, 0o644); os.chmod(LOG, 0o444)
    print(f"created empty log: {LOG} (mode 0444)")

def read_raw(path=LOG):
    p = Path(path)
    if not p.exists(): return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line: out.append(json.loads(line))
    return out

def head(records):
    return (records[-1]["seq"], link(records[-1])) if records else (0, GENESIS)

def append(agent, state, key=None, at_utc=None):
    key = key if key is not None else load_key()
    recs = read_raw()
    seq, prev = head(recs)
    rec = {
        "seq": seq + 1,
        "prev": prev,
        "at_utc": at_utc or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent": agent,
        "state": state,
    }
    rec["sig"] = sign(rec, key)
    os.chmod(LOG, 0o644)                      # unseal
    with open(LOG, "a") as f:
        f.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
        f.flush(); os.fsync(f.fileno())
    os.chmod(LOG, 0o444)                      # reseal
    return rec

def verify(records=None, key=None):
    """Returns (ok, problems). Chain checked always; signatures if key given."""
    records = read_raw() if records is None else records
    problems, prev = [], GENESIS
    for i, rec in enumerate(records):
        want_seq = i + 1
        if rec.get("seq") != want_seq:
            problems.append(f"seq {rec.get('seq')} at index {i}: expected {want_seq} (deletion or reorder)")
        if rec.get("prev") != prev:
            problems.append(f"seq {rec.get('seq')}: prev mismatch (record {i} chain broken)")
        if key is not None:
            if not hmac.compare_digest(sign(rec, key), rec.get("sig", "")):
                problems.append(f"seq {rec.get('seq')}: signature invalid (forged or key rotated)")
        prev = link(rec)
    return (len(problems) == 0), problems

if __name__ == "__main__":
    if "--init" in sys.argv:
        init(force="--force" in sys.argv)
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "append":
        # sink.py append <agent> '<state as JSON>'   (needs the writer key)
        if len(sys.argv) < 4:
            print("usage: sink.py append <agent> '<state JSON>'"); sys.exit(2)
        try:
            state = json.loads(sys.argv[3])
        except json.JSONDecodeError as e:
            print(f"state must be JSON: {e}"); sys.exit(2)
        try:
            rec = append(sys.argv[2], state)
        except FileNotFoundError as e:
            print(e); sys.exit(2)
        print(f"appended seq {rec['seq']} prev {rec['prev'][:16]}...")
        sys.exit(0)
    recs = read_raw()
    key = None
    if "--key" in sys.argv:
        try: key = load_key()
        except FileNotFoundError as e: print(e); sys.exit(2)
    ok, probs = verify(recs, key)
    seq, h = head(recs)
    print(f"records={len(recs)} head=seq {seq} {h[:16]}... signatures={'checked' if key else 'not checked'}")
    print("OK - chain intact" if ok else "FAIL")
    for p in probs: print("  !", p)
    sys.exit(0 if ok else 1)
