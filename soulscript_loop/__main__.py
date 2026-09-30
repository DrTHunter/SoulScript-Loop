"""CLI: python -m soulscript_loop --config config.json"""

import argparse
import asyncio
import logging
import sys

from .backend import backend_from_config
from .config import LoopConfig
from .runner import LoopRunner


def main():
    parser = argparse.ArgumentParser(prog="soulscript_loop", description="Run a persona's continuous loop.")
    parser.add_argument("--config", default="config.json", help="Path to loop config JSON")
    parser.add_argument("--echo", action="store_true", help="Use the offline echo backend (no API calls)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    config = LoopConfig.from_file(args.config)
    backend = backend_from_config({"type": "echo"} if args.echo else config.backend)
    runner = LoopRunner(config, backend)

    try:
        asyncio.run(runner.run())
    except KeyboardInterrupt:
        pass

    for entry in runner.state.journal_entries[-5:]:
        print(f"[loop {entry['loop']} tick {entry['tick']}] {entry['narrative']}")
    print(f"stopped: {runner.state.stop_reason} · ticks: {runner.state.total_ticks} · cost: ${runner.state.total_cost:.4f}")


if __name__ == "__main__":
    main()
