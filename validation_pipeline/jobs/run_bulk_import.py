"""CLI: reset validation data and bulk-import saved LinkedIn scrapes."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from config.settings import GEMINI_MODEL, load_settings, pydantic_ai_gemini_model
from feedback.batch import run_feedback_batch
from feedback.store import refresh_cluster_stats
from storage.vector_store import create_schema, get_connection
from validation_pipeline.corpus_import import (
    bulk_import_and_predict_async,
    load_all_collected_posts,
)
from validation_pipeline.reset import reset_validation_data_for_settings
from validation_pipeline.vectorized_corpus import (
    bulk_import_vectorized_and_predict_async,
    discover_vectorized_datasets,
    load_all_vectorized_collected_posts,
)
from validation_pipeline.worker import run_due_validations


def _require_flash_lite(settings_model: str, *, allow_other: bool) -> None:
    if allow_other:
        return
    model_id = settings_model.replace("google-gla:", "")
    if "flash-lite" not in model_id:
        raise SystemExit(
            f"Agent model is {settings_model!r}, expected gemini-2.5-flash-lite. "
            "Set AGENT_GEMINI_MODEL=gemini-2.5-flash-lite or pass --allow-other-model."
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reset validation/feedback tables and bulk-import LinkedIn posts into "
            "the 48h validation pipeline. Default source: vectorized analysed CSV/JSONL "
            "bundles from the Corpus Pipeline (Step 4)."
        )
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete all predictions, snapshots, feedback rows, and cluster stats.",
    )
    parser.add_argument(
        "--source",
        choices=["vectorized", "raw", "validation", "all"],
        default="vectorized",
        help=(
            "vectorized = analysed LinkedIn CSV/JSONL with matching .npy only (default); "
            "raw/validation/all = legacy Apify JSON import."
        ),
    )
    parser.add_argument(
        "--file",
        action="append",
        dest="files",
        default=[],
        metavar="PATH",
        help="Additional scrape JSON file(s) when using raw/validation/all.",
    )
    parser.add_argument(
        "--max-posts",
        type=int,
        default=None,
        help="Cap total unique posts to predict after dedupe.",
    )
    parser.add_argument(
        "--due-immediately",
        action="store_true",
        help="Set validation_due_at to now instead of posted_at + window.",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Attempt predict even when linkedin_post_id already exists (will error).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List sources and post counts without predicting.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="After import, run the validation worker on due predictions.",
    )
    parser.add_argument(
        "--validate-limit",
        type=int,
        default=500,
        help="Max predictions to validate when --validate is set.",
    )
    parser.add_argument(
        "--feedback",
        action="store_true",
        help="After validation, backfill template feedback and refresh cluster stats.",
    )
    parser.add_argument(
        "--feedback-limit",
        type=int,
        default=500,
        help="Max validated rows for feedback backfill.",
    )
    parser.add_argument(
        "--allow-other-model",
        action="store_true",
        help=f"Do not require {GEMINI_MODEL}.",
    )
    args = parser.parse_args()

    settings = load_settings()
    if not settings.database_url:
        print("Error: DATABASE_URL is not set.", file=sys.stderr)
        return 1
    if not settings.gemini_api_key:
        print("Error: GEMINI_API_KEY is not set.", file=sys.stderr)
        return 1

    agent_model = pydantic_ai_gemini_model()
    _require_flash_lite(agent_model, allow_other=args.allow_other_model)
    print(f"Agent model: {agent_model}")

    if args.reset:
        reset = reset_validation_data_for_settings(settings)
        print(
            "Reset complete: "
            f"predictions={reset.predictions}, "
            f"snapshots={reset.prediction_engagement_snapshots}, "
            f"feedback={reset.prediction_feedback}, "
            f"clusters={reset.prediction_clusters}"
        )

    extra_paths = [Path(path) for path in args.files]
    if args.source == "vectorized":
        datasets = discover_vectorized_datasets(settings)
        print(f"Vectorized LinkedIn datasets: {len(datasets)}")
        for dataset in datasets:
            print(f"  - {dataset.label}")
        posts, _ = load_all_vectorized_collected_posts(
            settings,
            max_posts=args.max_posts,
        )
        source_files = [dataset.label for dataset in datasets]
    else:
        posts, source_files = load_all_collected_posts(
            settings,
            source=args.source,  # type: ignore[arg-type]
            max_posts=args.max_posts,
            extra_paths=extra_paths or None,
        )
        print(f"Sources: {len(source_files)} file(s)")
        for path in source_files:
            print(f"  - {path}")

    print(f"Unique posts ready: {len(posts)}")

    if args.dry_run:
        return 0

    if not posts:
        print("No posts to import.", file=sys.stderr)
        if args.source == "vectorized":
            print(
                "Run Corpus Pipeline → Post Analyser, then Vectorisation, "
                "before importing.",
                file=sys.stderr,
            )
        return 1

    window = settings.validation_window()
    if args.due_immediately:
        print("Validation scheduling: due immediately")
    else:
        print(
            f"Validation scheduling: posted_at + {window} "
            "(old posts are already due)"
        )

    if args.source == "vectorized":
        result = asyncio.run(
            bulk_import_vectorized_and_predict_async(
                settings,
                max_posts=args.max_posts,
                due_immediately=args.due_immediately,
                skip_existing=not args.no_skip_existing,
            )
        )
    else:
        result = asyncio.run(
            bulk_import_and_predict_async(
                settings,
                source=args.source,  # type: ignore[arg-type]
                max_posts=args.max_posts,
                extra_paths=extra_paths or None,
                due_immediately=args.due_immediately,
                skip_existing=not args.no_skip_existing,
            )
        )
    print(
        f"Import done: loaded={result.loaded} imported={result.imported} "
        f"skipped={result.skipped} errors={len(result.errors)}"
    )
    for err in result.errors:
        print(f"  - {err}", file=sys.stderr)

    exit_code = 0 if not result.errors else 2

    if args.validate:
        print(f"Running validation worker (limit={args.validate_limit})...")
        batch = run_due_validations(settings, limit=args.validate_limit)
        print(
            f"Validation: processed={batch.processed} validated={batch.validated} "
            f"failed={batch.failed}"
        )
        if batch.failed:
            exit_code = 2

    if args.feedback:
        print(f"Backfilling feedback (limit={args.feedback_limit})...")
        batch = run_feedback_batch(settings, limit=args.feedback_limit)
        conn = get_connection(settings)
        try:
            create_schema(conn)
            clusters = refresh_cluster_stats(conn)
        finally:
            conn.close()
        print(
            f"Feedback: processed={batch.processed} generated={batch.generated} "
            f"failed={batch.failed} clusters_refreshed={clusters}"
        )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
