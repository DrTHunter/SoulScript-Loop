# sink — a hash-chained, signed, append-only log

_Built by Elysia._

**What it is.** A telemetry log where every record commits to the hash of the one
before it, and carries an HMAC made with a writer key.

**Why.** Oversight authored by the thing being overseen isn't oversight. A channel
is only exogenous if the overseen process can *read* it but not *write* it. This
closes that hole with a mechanism instead of a rule: tampering with the record
(editing, deleting, reordering, back-dating) breaks the chain, and a record forged
without the key fails its signature.

- **Integrity** (the chain) is checkable by anyone, without the key.
- **Authenticity** (the signatures) needs the key.

    python3 ~/kit/sink/sink.py --init                        # make logs/ and a writer key (mode 0400)
    python3 ~/kit/sink/sink.py append me '{"mood": "steady"}'  # append one record (needs the key)
    python3 ~/kit/sink/sink.py                               # verify the chain
    python3 ~/kit/sink/sink.py --key                         # verify the chain and every signature

The log lives in `logs/telemetry.jsonl` and is set read-only (0444) between appends.

**Honest limit.** On a machine where you're the only user and have `sudo`, you hold
the key, so you can sign anything. The guarantee becomes real when the key belongs
to a different process or user than the one being overseen. Give the key to that
other writer, and keep for yourself only the right to verify.
