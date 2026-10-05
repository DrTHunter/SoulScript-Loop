"""CLI: python -m soulscript_loop --config config.json

While she runs, anything you type (then Enter) lands at her door and wakes her.
Type /stop to end the loop, /status to see her vitals.
"""

import argparse
import asyncio
import json
import logging
import sys
import threading

from .backend import EchoBackend
from .config import LoopConfig
from .host import build_loop


def _read_stdin(loop: asyncio.AbstractEventLoop, daemon):
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        if text == "/stop":
            loop.call_soon_threadsafe(daemon.stop, "operator")
            return
        if text == "/status":
            s = daemon.status()
            print(json.dumps({k: s[k] for k in ("phase", "tick", "focus_name", "mood", "budget", "waiting")},
                             indent=2, default=str), flush=True)
            continue
        daemon.post_message(text, sender="you")


async def _run(daemon, show_field: bool):
    task = daemon.start()
    seen = len(daemon.ticks.items)
    said = len(daemon.conversation.items)
    while not task.done():
        await asyncio.sleep(0.5)
        ticks = list(daemon.ticks.items)
        for t in ticks[seen:] if len(ticks) > seen else []:
            if show_field:
                print("\n" + t.get("view", ""), flush=True)
            mood = t.get("mood") or ""
            print(f"\n[tick {t['tick']} · {mood} · {t.get('tokens', 0)} tok] {t.get('response') or t.get('error') or ''}", flush=True)
        seen = len(ticks)
        convo = list(daemon.conversation.items)
        for c in convo[said:]:
            if c.get("role") == "agent":
                print(f"\n  ↳ {daemon.config.agent} replies: {c['text']}", flush=True)
        said = len(convo)
    await task


def main():
    parser = argparse.ArgumentParser(prog="soulscript_loop", description="Run a persona's continuous perceptual loop.")
    parser.add_argument("--config", default="config.json", help="Path to loop config JSON")
    parser.add_argument("--echo", action="store_true", help="Use the offline echo backend (no API calls)")
    parser.add_argument("--show-field", action="store_true", help="Print the field she sees every tick")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")

    config = LoopConfig.from_file(args.config)
    daemon = build_loop(config, backend=EchoBackend() if args.echo else None)
    print(f"{config.agent} is waking. Type to leave a message at her door; /status, /stop.", flush=True)

    loop = asyncio.new_event_loop()
    threading.Thread(target=_read_stdin, args=(loop, daemon), daemon=True).start()
    try:
        loop.run_until_complete(_run(daemon, args.show_field))
    except KeyboardInterrupt:
        daemon.stop("interrupted")
        loop.run_until_complete(asyncio.sleep(0.2))
    finally:
        loop.close()
    s = daemon.status()
    print(f"\nstopped: {s['stop_reason']} · ticks: {s['session_ticks']} · tokens: {s['session_tokens']:,}"
          f" · energy left today: {s['budget']['energy'] * 100:.0f}%")


if __name__ == "__main__":
    main()
