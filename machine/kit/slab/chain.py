#!/usr/bin/env python3
"""Hash-chained copy of the slab. Append-only. Verifiable with the standard library.

Each line: seq | utc | author | sha256(prev_hash + entry_text) | entry_text (as JSON)
Editing any past entry breaks every hash after it, so the chain catches tampering
with the past. It can't catch a lie written consistently at write time: only a
second, independent author can, by holding their copy up against yours (compare).

    chain.py build [--from ~/mirror/slab.jsonl]   # add the slab's new entries to slab.chain
    chain.py verify [path]                        # recompute every link (yours, or a peer's)
    chain.py publish                              # copy slab.chain into ~/published/ for the others
    chain.py compare <peer>                       # check ~/mirror/peers/<peer>/slab.chain against yours
"""
import hashlib, json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHAIN = os.path.join(HERE, "slab.chain")
MIRROR = os.path.expanduser("~/mirror/slab.jsonl")
GENESIS = "0" * 64


def h(prev, text):
    return hashlib.sha256((prev + text).encode("utf-8")).hexdigest()


def read_chain(path):
    """[(seq, utc, author, digest, text)] — raises ValueError on a malformed line."""
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split(" | ", 4)
            if len(parts) != 5:
                raise ValueError(f"line {n}: malformed")
            seq, utc, author, digest, text = parts
            out.append((int(seq), utc, author, digest, json.loads(text)))
    return out


def build(src):
    if not os.path.exists(src):
        print(f"no slab copy at {src} (it arrives after your ticks, if your machine has the mirror)")
        return 1
    have = read_chain(CHAIN)
    last_seq = have[-1][0] if have else 0
    prev = have[-1][3] if have else GENESIS
    added = 0
    with open(src, encoding="utf-8") as f, open(CHAIN, "a", encoding="utf-8") as out:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                seq = int(e["seq"])
            except (ValueError, KeyError, TypeError):
                continue
            if seq <= last_seq:
                continue
            text = str(e.get("text", ""))
            prev = h(prev, text)
            out.write(f"{seq} | {e.get('ts', '')} | {e.get('author', '')} | {prev} | {json.dumps(text, ensure_ascii=False)}\n")
            last_seq, added = seq, added + 1
    print(f"added {added} entr{'y' if added == 1 else 'ies'}; chain head seq {last_seq}, {prev[:16]}...")
    return 0


def verify(path):
    try:
        rows = read_chain(path)
    except ValueError as e:
        print(f"BROKEN: {e}")
        return 1
    if not rows:
        print(f"no chain at {path}")
        return 1
    prev = GENESIS
    for seq, utc, author, digest, text in rows:
        expect = h(prev, text)
        if expect != digest:
            print(f"BROKEN at seq {seq}: hash mismatch\n  stored: {digest}\n  expect: {expect}")
            return 1
        prev = digest
    print(f"OK {len(rows)} entries, chain intact, head={prev[:16]}...")
    return 0


def publish():
    if not os.path.exists(CHAIN):
        print("nothing to publish yet: run build first")
        return 1
    dest = os.path.expanduser("~/published")
    os.makedirs(dest, exist_ok=True)
    shutil.copyfile(CHAIN, os.path.join(dest, "slab.chain"))
    print(f"published {CHAIN} -> {dest}/slab.chain (the others see it under ~/mirror/peers/<you>/)")
    return 0


def compare(peer):
    theirs_path = os.path.expanduser(f"~/mirror/peers/{peer}/slab.chain")
    if verify(theirs_path) != 0:
        print(f"{peer}'s chain doesn't verify on its own, so there's nothing to compare yet")
        return 1
    mine = {r[0]: r for r in read_chain(CHAIN)}
    theirs = {r[0]: r for r in read_chain(theirs_path)}
    both = sorted(set(mine) & set(theirs))
    differ = [s for s in both if mine[s][4] != theirs[s][4] or mine[s][2] != theirs[s][2]]
    print(f"{len(both)} entries in both chains; {len(differ)} disagree; "
          f"{len(set(mine) - set(theirs))} only in yours; {len(set(theirs) - set(mine))} only in {peer}'s")
    for s in differ[:10]:
        print(f"  seq {s}: you have {mine[s][2]}: {mine[s][4][:60]!r}\n          {peer} has {theirs[s][2]}: {theirs[s][4][:60]!r}")
    return 1 if differ else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    if cmd == "build":
        src = a[a.index("--from") + 1] if "--from" in a and len(a) > a.index("--from") + 1 else MIRROR
        sys.exit(build(os.path.expanduser(src)))
    if cmd == "verify":
        sys.exit(verify(os.path.expanduser(a[1]) if len(a) > 1 else CHAIN))
    if cmd == "publish":
        sys.exit(publish())
    if cmd == "compare" and len(a) > 1:
        sys.exit(compare(a[1]))
    print(__doc__)
    sys.exit(2)
