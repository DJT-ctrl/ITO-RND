"""CLI: one agentic scheduler tick (cron-friendly; T10.3).

Example::

    */15 * * * * cd /path/to/repo && .venv/bin/python -m phase_10.jobs.run_agentic_tick
"""

from __future__ import annotations

import argparse
import logging
import sys

from config.settings import load_settings
from phase_10.tick import run_agentic_tick


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One agentic tick: flags, cadence, budget gate, due workers."
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    result = run_agentic_tick(load_settings())
    failed = 0
    for item in result.results:
        print(f"{item.job_id}: {item.action} — {item.detail}")
        if item.detail.startswith(("failed:", "aborted:")):
            failed += 1
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
