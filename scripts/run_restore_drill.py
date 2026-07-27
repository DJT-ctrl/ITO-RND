#!/usr/bin/env python3
"""Time a Postgres restore drill and write docs/ops/RESTORE_DRILL_LATEST.json (#15).

Live (destructive to the target DB — use non-prod):
  python scripts/run_restore_drill.py --dump data/db_backups/posts_daily_….dump

CI / docs simulation (no Docker):
  python scripts/run_restore_drill.py --simulate
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.settings import load_settings  # noqa: E402
from storage.dr_backup import (  # noqa: E402
    DEFAULT_DRILL_REPORT,
    run_restore_drill,
    simulate_restore_drill_timings,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", type=Path, default=None, help="Path to .dump for live restore")
    parser.add_argument("--simulate", action="store_true", help="Write simulated drill report")
    parser.add_argument("--report", type=Path, default=Path(DEFAULT_DRILL_REPORT))
    parser.add_argument("--rpo-hours", type=float, default=24.0)
    parser.add_argument("--rto-hours", type=float, default=4.0)
    args = parser.parse_args(argv)

    rpo = int(args.rpo_hours * 3600)
    rto = int(args.rto_hours * 3600)

    if args.simulate:
        payload = simulate_restore_drill_timings(
            rpo_target_seconds=rpo,
            rto_target_seconds=rto,
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2))
        return 0

    if args.dump is None:
        parser.error("pass --dump PATH or --simulate")

    settings = load_settings()
    result = run_restore_drill(
        settings,
        args.dump,
        rpo_target_seconds=rpo,
        rto_target_seconds=rto,
        report_path=args.report,
        notes="Live non-prod restore drill (issue #15)",
        perform_restore=True,
    )
    print(json.dumps(result.__dict__, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
