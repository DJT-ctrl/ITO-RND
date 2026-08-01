"""Batch entry point for T1.4/T1.5: load the ingredients T1.2/T1.3 already
produced (processed JSONL + matching .npy embeddings) into Postgres+pgvector.

Reuses processors/run_embeddings.load_and_join() so the exact same
dataset-resolution + raw-content-joining logic is used here as when the
embeddings were generated - and applies the identical word_count >= 10 /
non-blank-content filter so records line up index-for-index with the
embeddings loaded from the .npy file.

Usage:
    python -m processors.run_db_ingest
    python -m processors.run_db_ingest --processed-file data/processed/linkedin_20260704T205635Z.jsonl \
        --embeddings-file data/embeddings/linkedin_gemini_20260705T022011Z.npy

NOTE: requires a reachable Postgres+pgvector instance (DATABASE_URL in .env).
See T1.4_DATABASE_PLAN.md - this script is Phase 1 code, meant to be run
once Phase 2 (docker-compose up, on EC2 or locally) has a live database.

The Streamlit **Make embeddings** page also calls ``ingest_embedded_records``
right after a successful embed so the retrieval corpus stays in sync without
a separate CLI step.
"""

import argparse
import glob
import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np

from config.settings import Settings, load_settings
from processors.run_embeddings import load_and_join
from storage.db_backup import create_backup
from storage.pipeline_registry import register_ingest_bundle
from storage.vector_store import create_schema, get_connection, insert_posts

logger = logging.getLogger(__name__)


def _latest_npy(embeddings_dir: str = "data/embeddings") -> Path:
    """Return the most recent linkedin_gemini_*.npy file under embeddings_dir."""
    files = sorted(glob.glob(f"{embeddings_dir}/linkedin_gemini_*.npy"))
    if not files:
        raise ValueError(f"No embedding files found under {embeddings_dir}/linkedin_gemini_*.npy")
    return Path(files[-1])


def _maybe_backup(settings: Settings, *, skip_backup: bool) -> None:
    """Take a pre-ingest dump when possible; soft-skip if Compose ``db`` is down."""
    if skip_backup:
        return
    try:
        backup_path = create_backup(settings)
        print(f"Backed up posts table to {backup_path} before ingesting.")
    except RuntimeError as exc:
        # Local Postgres often runs outside docker-compose; backup requires
        # `docker compose exec db pg_dump`. Don't block ingest for that.
        msg = str(exc)
        if "is not running" in msg or "pg_dump failed" in msg:
            warning = f"Pre-ingest backup skipped ({exc}). Continuing without backup."
            print(warning)
            logger.warning(warning)
            return
        raise


def ingest_embedded_records(
    records: list[dict[str, Any]],
    vectors: np.ndarray,
    *,
    settings: Optional[Settings] = None,
    bundle_id: Optional[str] = None,
    skip_backup: bool = True,
) -> int:
    """Upsert an already-embedded batch (records[i] ↔ vectors[i]) into Postgres.

    Used by the dashboard right after ``embed_batch`` so subset runs and full
    runs both land in the retrieval corpus without re-loading a .npy that may
    not match every eligible row in the analysed JSONL.

    Returns the number of rows upserted.
    """
    settings = settings or load_settings()
    if not settings.database_url:
        raise ValueError("DATABASE_URL is not set — cannot ingest into Postgres.")
    if len(records) != len(vectors):
        raise ValueError(
            f"records ({len(records)}) and vectors ({len(vectors)}) length mismatch"
        )
    if not records:
        return 0

    _maybe_backup(settings, skip_backup=skip_backup)

    conn = get_connection(settings)
    try:
        create_schema(conn)
        count = insert_posts(conn, records, vectors)
    finally:
        conn.close()

    if bundle_id:
        register_ingest_bundle(bundle_id=bundle_id, ingested_count=count)

    print(f"Upserted {count} embedded posts into Postgres")
    return count


def run_db_ingest(
    processed_file: Optional[str] = None,
    embeddings_file: Optional[str] = None,
    settings: Optional[Settings] = None,
    skip_backup: bool = False,
) -> int:
    """Run the full T1.4/T1.5 batch: backup -> load -> join -> filter -> upsert into Postgres.

    A full-database dump is taken via storage/db_backup.py BEFORE anything
    is written, so a bad ingestion run can always be rolled back to the
    state right before it ran (see storage/db_backup.py for why this is
    the reliable rollback mechanism given insert_posts() upserts in place).
    Set ``skip_backup=True`` to skip this (e.g. fast local iteration/tests
    against a throwaway DB) — real runs should not pass this.

    If Compose ``db`` is not running, the backup is skipped with a warning
    and ingest still proceeds (common for local Postgres outside Docker).

    Returns the number of rows upserted.
    """
    settings = settings or load_settings()

    _maybe_backup(settings, skip_backup=skip_backup)

    joined_records, jsonl_path, _ = load_and_join(processed_file, settings)

    # Re-apply embedder.py's exact eligibility filter so records line up
    # 1:1 with the vectors already saved to the .npy file.
    valid_records = [
        record
        for record in joined_records
        if (record.get("content") or "").strip() and record.get("word_count", 0) >= 10
    ]

    npy_path = Path(embeddings_file) if embeddings_file else _latest_npy()
    vectors = np.load(npy_path)

    if len(valid_records) != len(vectors):
        raise ValueError(
            f"{jsonl_path.name} has {len(valid_records)} eligible posts but {npy_path.name} "
            f"has {len(vectors)} vectors - they must come from the same embedding run."
        )

    count = ingest_embedded_records(
        valid_records,
        vectors,
        settings=settings,
        skip_backup=True,  # already handled above
    )

    print(f"Upserted {count} posts from {jsonl_path.name} + {npy_path.name} into Postgres")

    from storage.pipeline_registry import bundles_for_analysed_files

    bundles = bundles_for_analysed_files([jsonl_path.name])
    if bundles:
        register_ingest_bundle(bundle_id=bundles[0].bundle_id, ingested_count=count)

    return count


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--processed-file",
        default=None,
        help="Path to a specific processed JSONL file (defaults to the latest under data/processed/).",
    )
    parser.add_argument(
        "--embeddings-file",
        default=None,
        help="Path to a specific .npy embeddings file (defaults to the latest under data/embeddings/).",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Skip the pre-ingestion pg_dump backup (default: a backup is always taken first).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_db_ingest(
        processed_file=args.processed_file,
        embeddings_file=args.embeddings_file,
        skip_backup=args.skip_backup,
    )
