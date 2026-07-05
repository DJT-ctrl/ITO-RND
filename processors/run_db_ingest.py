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
"""

import argparse
import glob
from pathlib import Path
from typing import Optional

import numpy as np

from config.settings import Settings, load_settings
from processors.run_embeddings import load_and_join
from storage.vector_store import create_schema, get_connection, insert_posts


def _latest_npy(embeddings_dir: str = "data/embeddings") -> Path:
    """Return the most recent linkedin_gemini_*.npy file under embeddings_dir."""
    files = sorted(glob.glob(f"{embeddings_dir}/linkedin_gemini_*.npy"))
    if not files:
        raise ValueError(f"No embedding files found under {embeddings_dir}/linkedin_gemini_*.npy")
    return Path(files[-1])


def run_db_ingest(
    processed_file: Optional[str] = None,
    embeddings_file: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> int:
    """Run the full T1.4/T1.5 batch: load -> join -> filter -> upsert into Postgres.

    Returns the number of rows upserted.
    """
    settings = settings or load_settings()
    joined_records, jsonl_path = load_and_join(processed_file, settings)

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

    conn = get_connection(settings)
    try:
        create_schema(conn)
        count = insert_posts(conn, valid_records, vectors)
    finally:
        conn.close()

    print(f"Upserted {count} posts from {jsonl_path.name} + {npy_path.name} into Postgres")
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
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_db_ingest(processed_file=args.processed_file, embeddings_file=args.embeddings_file)
