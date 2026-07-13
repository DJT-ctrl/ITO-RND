"""CLI entry point for the four-arm held-out feedback evaluation."""

from __future__ import annotations

import argparse

from config.settings import load_settings
from feedback.evaluation_runner import run_and_save_offline_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--holdout-size",
        type=int,
        default=30,
        help="Number of stable-hash selected validated rows held out from training.",
    )
    args = parser.parse_args()
    settings = load_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is not set.")

    try:
        report, path = run_and_save_offline_evaluation(
            settings,
            holdout_size=args.holdout_size,
        )
    except ValueError as exc:
        raise SystemExit(f"Evaluation not run: {exc}") from exc
    print(
        f"Saved {len(report.arms)} arms; holdout={report.holdout_rows}; "
        f"training={report.training_rows}; path={path}"
    )


if __name__ == "__main__":
    main()
