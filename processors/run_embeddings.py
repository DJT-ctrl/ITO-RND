"""Batch entry point for T1.3: Vector Embedding Generation.

Loads the latest consolidated dataset from data/processed/ (or a specific
file via --processed-file), re-joins each record's raw post `content` by
post_id (NormalizedPost — processors/schemas.py — is a feature-only schema
with `extra="forbid"` and deliberately carries no `content` field), embeds
every valid post through Gemini (processors/embedder.py), and saves the
resulting vectors to data/embeddings/.

Usage:
    python -m processors.run_embeddings
    python -m processors.run_embeddings --processed-file data/processed/linkedin_20260704T205635Z.jsonl
    python -m processors.run_embeddings --limit 10   # cheap manual test run
"""

import argparse
import glob
import json
from pathlib import Path
from typing import Optional

from config.settings import Settings, load_settings
from processors.embedder import embed_batch, save_embeddings
from processors.run_pipeline import load_raw_posts


def _latest_jsonl(processed_dir: str = "data/processed") -> Path:
    """Return the most recent linkedin_*.jsonl file under processed_dir."""
    files = sorted(glob.glob(f"{processed_dir}/linkedin_*.jsonl"))
    if not files:
        raise ValueError(f"No processed JSONL files found under {processed_dir}/linkedin_*.jsonl")
    return Path(files[-1])


def _load_processed_records(jsonl_path: Path) -> list[dict]:
    with jsonl_path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def _join_content(records: list[dict], raw_data_dir: str) -> list[dict]:
    """Re-attach raw post `content` to each processed record by post_id.

    NormalizedPost has no `content` field, so it must be pulled back from
    the raw scrape files the same way processors/run_pipeline.py reads them.
    """
    raw_posts = load_raw_posts(raw_data_dir)
    content_by_id = {post.get("id") or "": post.get("content") or "" for post in raw_posts}
    return [{**record, "content": content_by_id.get(record["post_id"], "")} for record in records]


def load_and_join(processed_file: Optional[str], settings: Settings) -> tuple[list[dict], Path]:
    """Load a processed dataset and re-join raw `content` by post_id.

    Shared by ``run_embeddings()`` (CLI) and the Vectorisation dashboard page
    so both pick the exact same dataset resolution + content joining logic.

    Returns:
        (joined_records, jsonl_path_used) — the path is returned so callers
        can show the user exactly which file was read.
    """
    jsonl_path = Path(processed_file) if processed_file else _latest_jsonl()
    records = _load_processed_records(jsonl_path)
    joined_records = _join_content(records, settings.raw_data_dir)
    return joined_records, jsonl_path


def run_embeddings(
    processed_file: Optional[str] = None,
    settings: Optional[Settings] = None,
    limit: Optional[int] = None,
) -> Path:
    """Run the full T1.3 batch: load -> join content -> embed -> save.

    ``settings``/``processed_file`` are injectable so tests can point this
    at temp files instead of the real data/processed + data/raw directories.

    ``limit`` caps how many (post-join) records are sent to the embedding
    endpoint — useful for a cheap manual test run before embedding an entire
    dataset. ``None`` (default) embeds every eligible record.
    """
    settings = settings or load_settings()
    joined_records, _ = load_and_join(processed_file, settings)
    if limit is not None:
        joined_records = joined_records[:limit]

    vectors, skipped = embed_batch(joined_records, settings)
    print(f"Embedded {len(vectors)} posts, skipped {skipped} (word_count < 10 or empty content)")

    return save_embeddings(vectors, "linkedin")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--processed-file",
        default=None,
        help="Path to a specific processed JSONL file (defaults to the latest under data/processed/).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only embed the first N eligible posts (manual/cheap test run). Default: embed everything.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    out_path = run_embeddings(processed_file=args.processed_file, limit=args.limit)
    print(f"Wrote {out_path}")
