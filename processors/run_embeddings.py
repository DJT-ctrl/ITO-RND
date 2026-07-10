"""Batch entry point for T1.3: Vector Embedding Generation.

Loads one or more consolidated ``linkedin_analysed_*.jsonl`` datasets,
re-joins each record's raw post ``content`` scoped to the bundle's source
scraper file(s), embeds every valid post through Gemini, and saves vectors
with a sidecar manifest linking back to the analysed dataset(s).

Usage:
    python -m processors.run_embeddings
    python -m processors.run_embeddings --processed-file data/processed/linkedin_analysed_2026-07-10_120000Z.jsonl
    python -m processors.run_embeddings --limit 10   # cheap manual test run
"""

import argparse
from pathlib import Path
from typing import Optional

from config.settings import Settings, load_settings
from processors.embedder import embed_batch, save_embeddings
from storage.pipeline_registry import (
    bundles_for_analysed_files,
    join_content_to_records,
    merge_source_scans_from_bundles,
    register_embeddings_bundle,
)


def _latest_jsonl(processed_dir: str = "data/processed") -> Path:
    """Return the most recent linkedin_analysed_*.jsonl file under processed_dir."""
    from config.paths import resolve_data_path
    from processors.finalize_records import list_analysed_datasets

    files = list_analysed_datasets(resolve_data_path(processed_dir))
    if not files:
        raise ValueError(
            f"No analysed JSONL files found under {processed_dir}/linkedin_analysed_*.jsonl. "
            "Run Post Analyser (Stage 1 + 2) or "
            "`python -m processors.run_pipeline --with-gemini` first."
        )
    return files[0]


def load_and_join(
    processed_file: Optional[str] = None,
    settings: Optional[Settings] = None,
    *,
    processed_files: Optional[list[str]] = None,
) -> tuple[list[dict], Path, list[str]]:
    """Load analysed dataset(s) and re-join raw ``content`` by post_id.

    When multiple JSONL paths are given, records are merged by ``post_id``.
    Content is always joined using the union of source scraper files recorded
    in the pipeline bundle registry (not every file in ``data/raw/``).

    Returns:
        (joined_records, primary_jsonl_path, source_scans)
    """
    settings = settings or load_settings()

    if processed_files:
        paths = [Path(p) for p in processed_files]
    elif processed_file:
        paths = [Path(processed_file)]
    else:
        paths = [_latest_jsonl()]

    from processors.finalize_records import load_analysed_jsonl
    from storage.pipeline_registry import dedupe_records_by_post_id

    filenames = [p.name for p in paths]
    records: list[dict] = []
    for path in paths:
        records.extend(load_analysed_jsonl(path))
    records = dedupe_records_by_post_id(records)
    bundles = bundles_for_analysed_files(filenames)
    source_scans = merge_source_scans_from_bundles(bundles)
    if not source_scans:
        # Legacy analysed files without registry — fall back to all raw scans.
        from processors.run_pipeline import load_raw_posts

        raw_posts = load_raw_posts(settings.raw_data_dir)
        content_by_id = {post.get("id") or "": post.get("content") or "" for post in raw_posts}
        joined = [{**r, "content": content_by_id.get(r["post_id"], "")} for r in records]
    else:
        joined = join_content_to_records(
            records, source_scans=source_scans, raw_data_dir=settings.raw_data_dir
        )

    return joined, paths[0], source_scans


def run_embeddings(
    processed_file: Optional[str] = None,
    settings: Optional[Settings] = None,
    limit: Optional[int] = None,
    *,
    processed_files: Optional[list[str]] = None,
    bundle_id: Optional[str] = None,
) -> Path:
    """Run the full T1.3 batch: load -> join content -> embed -> save + register."""
    settings = settings or load_settings()
    joined_records, jsonl_path, _ = load_and_join(
        processed_file, settings, processed_files=processed_files
    )
    if limit is not None:
        joined_records = joined_records[:limit]

    vectors, skipped = embed_batch(joined_records, settings)
    print(f"Embedded {len(vectors)} posts, skipped {skipped} (word_count < 10 or empty content)")

    out_path = save_embeddings(vectors, "linkedin")
    eligible = [
        r
        for r in joined_records
        if (r.get("content") or "").strip() and r.get("word_count", 0) >= 10
    ]
    post_ids = [r["post_id"] for r in eligible[: len(vectors)]]

    bundles = bundles_for_analysed_files(
        [p.name for p in ([Path(f) for f in processed_files] if processed_files else [jsonl_path])]
    )
    resolved_bundle_id = bundle_id or (bundles[0].bundle_id if bundles else None)
    if resolved_bundle_id:
        register_embeddings_bundle(
            bundle_id=resolved_bundle_id,
            embeddings_npy=str(out_path),
            embedding_post_ids=post_ids,
            source_jsonl=jsonl_path.name,
        )

    return out_path


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
