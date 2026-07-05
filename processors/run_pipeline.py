"""Batch entry point that finishes T1.2: normalization + engagement benchmark.

This is the real pipeline the product depends on — deliberately separate
from ``dashboard/pages/3_Post_Analyser.py``, which stays a throwaway
interactive harness for testing one saved scan at a time.

What it does, in order:
  1. Load every raw post scan in data/raw/linkedin_*.json (profile scans
     are skipped — different record shape, merged in separately).
  2. Stage 1 — per-post Python features (free, instant, always run).
  3. Batch step — engagement benchmark (needs the whole set at once,
     see processors/benchmark.py for why this can't be per-post).
  4. Stage 2 — Gemini qualitative tags (optional, one API call per post,
     only runs with --with-gemini since it costs money).
  5. Validate every record against NormalizedPost (processors/schemas.py)
     so a broken row fails loudly here instead of downstream in T1.3.
  6. Persist ONE consolidated dataset in both CSV and JSONL
     (storage/processed_store.py).

Usage:
    python -m processors.run_pipeline                # Stage 1 + benchmark only
    python -m processors.run_pipeline --with-gemini   # + Stage 2 Gemini tags
"""

import argparse
import glob
import json
from pathlib import Path
from typing import Optional

from config.settings import Settings, load_settings
from processors.benchmark import add_engagement_benchmark
from processors.post_analyser import PostAnalyser
from processors.schemas import NormalizedPost
from storage.processed_store import ProcessedStore


def load_raw_posts(raw_data_dir: str) -> list[dict]:
    """Read and concatenate every post scan under raw_data_dir.

    Only files matching ``linkedin_*.json`` are considered, and
    ``linkedin_profiles_*.json`` scans are explicitly excluded — those hold
    author profile records (a different shape entirely), not posts. Profile
    data is merged in separately, the same way the Streamlit harness does
    it (see ``_load_profile_lookup`` in dashboard/pages/3_Post_Analyser.py).
    """
    posts: list[dict] = []
    for path in sorted(glob.glob(f"{raw_data_dir}/linkedin_*.json")):
        if "profiles" in Path(path).name:
            continue
        posts.extend(json.loads(Path(path).read_text()))
    return posts


def run_pipeline(
    with_gemini: bool = False,
    settings: Optional[Settings] = None,
    store: Optional[ProcessedStore] = None,
) -> tuple[Path, Path]:
    """Run the full T1.2 batch pipeline and return (csv_path, jsonl_path).

    ``settings``/``store`` are injectable purely so tests can point the
    pipeline at a temp directory instead of the real data/raw + data/processed.
    """
    settings = settings or load_settings()
    store = store or ProcessedStore()
    analyser = PostAnalyser(settings)

    raw_posts = load_raw_posts(settings.raw_data_dir)
    if not raw_posts:
        raise ValueError(f"No raw posts found under {settings.raw_data_dir}/linkedin_*.json")

    # Stage 1: per-post features, always run — free and instant.
    stage1_records = [analyser.compute_python_features(post) for post in raw_posts]

    # Batch step: benchmark needs every post's total_engagement at once.
    records = add_engagement_benchmark(stage1_records)

    # Stage 2: optional, costs one Gemini API call per post.
    if with_gemini:
        for post, record in zip(raw_posts, records):
            record.update(analyser.compute_gemini_features(post, record))

    # Fail loudly here rather than writing a malformed row that T1.3 chokes on later.
    validated_records = [NormalizedPost.model_validate(record).model_dump() for record in records]

    csv_path = store.save("linkedin", validated_records)
    jsonl_path = store.save_jsonl("linkedin", validated_records)
    return csv_path, jsonl_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-gemini",
        action="store_true",
        help="Also run Stage 2 (Gemini qualitative tags) — one API call per post.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    csv_path, jsonl_path = run_pipeline(with_gemini=args.with_gemini)
    print(f"Wrote {csv_path}")
    print(f"Wrote {jsonl_path}")
