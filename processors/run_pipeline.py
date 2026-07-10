"""Batch entry point that finishes T1.2: normalization + engagement benchmark.

This is the real pipeline the product depends on — deliberately separate
from ``dashboard/pages/2_Post_Analyser.py``, which stays a throwaway
interactive harness for testing one saved scan at a time.

What it does, in order:
  1. Load every raw post scan in data/raw/linkedin_*.json (profile scans
     are skipped — different record shape, merged in separately).
  2. Remove exact-duplicate content (processors/dedup.py).
  2b. OPTIONAL (--with-profile-enrichment): merge a saved profile scrape
      (processors/profile_sources.py + processors/profile_enricher.py) onto
      every raw post BEFORE Stage 1, so follower count / location feed into
      Stage 1 features below. Off by default — the pipeline is byte-for-byte
      identical to before this feature existed unless explicitly requested.
  3. Stage 1 — per-post Python features (free, instant, always run). When
     profile enrichment merged in follower/location data, this also emits
     follower_count / author_location_text / author_timezone /
     engagement_rate and computes hour_of_day/day_of_week in the author's
     local time instead of UTC (processors/post_timing.py).
  4. Batch step — engagement benchmark (needs the whole set at once,
     see processors/benchmark.py for why this can't be per-post). With
     --with-profile-enrichment, an additional audience-adjusted benchmark
     (follower-normalized) is computed alongside the raw one.
  5. Stage 2 — Gemini qualitative tags (optional, one API call per post,
     only runs with --with-gemini since it costs money).
  6. Flag statistically implausible engagement ratios
     (processors/benchmark.py::flag_engagement_anomalies) — flagged posts
     are held out of the main dataset into a separate review file.
  7. Validate every remaining record against NormalizedPost
     (processors/schemas.py) so a broken row fails loudly here instead of
     downstream in T1.3.
  8. Persist the clean dataset in both CSV and JSONL
     (storage/processed_store.py), plus a separate JSONL for flagged posts
     if any exist.

Usage:
    python -m processors.run_pipeline                        # Stage 1 + benchmark only
    python -m processors.run_pipeline --with-gemini           # + Stage 2 Gemini tags
    python -m processors.run_pipeline --with-profile-enrichment  # + follower-normalized benchmark + local posting time
"""

import argparse
import glob
import json
from pathlib import Path
from typing import Optional

from config.settings import Settings, load_settings
from processors.benchmark import (
    add_audience_adjusted_benchmark,
    add_engagement_benchmark,
    flag_engagement_anomalies,
)
from processors.corpus_benchmarks import build_snapshot, save_snapshot
from processors.dedup import dedupe_posts
from processors.post_analyser import PostAnalyser
from processors.profile_enricher import enrich_posts_with_follower_data
from processors.profile_sources import load_profile_records
from processors.schemas import NormalizedPost
from storage.processed_store import ProcessedStore


def load_raw_posts(raw_data_dir: str) -> list[dict]:
    """Read and concatenate every post scan under raw_data_dir.

    Only files matching ``linkedin_*.json`` are considered, and
    ``linkedin_profiles_*.json`` scans are explicitly excluded — those hold
    author profile records (a different shape entirely), not posts. Profile
    data is merged in separately, the same way the Streamlit harness does
    it (see profile auto-pairing in dashboard/pages/2_Post_Analyser.py).
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
    with_profile_enrichment: bool = False,
    profile_file: Optional[str] = None,
) -> tuple[Path, Path]:
    """Run the full T1.2 batch pipeline and return (csv_path, jsonl_path).

    ``settings``/``store`` are injectable purely so tests can point the
    pipeline at a temp directory instead of the real data/raw + data/processed.

    ``with_profile_enrichment`` is the OPTIONAL follower-normalization path
    (T6 Point 1): when True, a saved profile scrape (``profile_file``, or
    the latest ``linkedin_profiles_*.json`` under ``settings.raw_data_dir``
    if omitted) is merged onto every raw post BEFORE Stage 1 runs, and an
    additional audience-adjusted benchmark is computed. Raises ``ValueError``
    if no profile scrape can be found — partial author coverage within a
    found scrape is fine (some authors just won't get follower/location
    data), but running this flag with NO profile data at all is treated as
    a usage error, not a silent no-op. When False (default), behavior is
    unchanged from before this feature existed.
    """
    settings = settings or load_settings()
    store = store or ProcessedStore()
    analyser = PostAnalyser(settings)

    raw_posts = load_raw_posts(settings.raw_data_dir)
    if not raw_posts:
        raise ValueError(f"No raw posts found under {settings.raw_data_dir}/linkedin_*.json")

    # Remove exact-duplicate content BEFORE Stage 1/benchmark — both are
    # indexed 1:1 off raw_posts, and duplicate content would otherwise
    # double-count in the engagement benchmark and anomaly-detection stats.
    raw_posts, num_duplicates_removed = dedupe_posts(raw_posts)
    if num_duplicates_removed:
        print(f"Removed {num_duplicates_removed} exact-duplicate post(s) before analysis.")

    if with_profile_enrichment:
        profile_records = load_profile_records(
            profile_file, settings.raw_data_dir, allow_empty=True
        )
        raw_posts = enrich_posts_with_follower_data(raw_posts, profile_records)
        matched = sum(1 for p in raw_posts if p.get("follower_count"))
        print(
            f"Profile enrichment: {matched}/{len(raw_posts)} post(s) matched to a "
            "follower count (business authors are free; unmatched personal authors "
            "simply won't get follower-normalized fields)."
        )

    # Stage 1: per-post features, always run — free and instant.
    stage1_records = [analyser.compute_python_features(post) for post in raw_posts]

    # Batch step: benchmark needs every post's total_engagement at once.
    records = add_engagement_benchmark(stage1_records)
    if with_profile_enrichment:
        records = add_audience_adjusted_benchmark(records)

    # Stage 2: optional, costs one Gemini API call per post.
    if with_gemini:
        for post, record in zip(raw_posts, records):
            record.update(analyser.compute_gemini_features(post, record))

    # Flag statistically implausible engagement ratios (e.g. bot/engagement-
    # pod pollution). Flagged posts are held OUT of the main dataset and
    # written to a separate review file instead — see
    # processors/benchmark.py::flag_engagement_anomalies for the detection
    # logic and /memories/session/plan.md for why this isn't auto-excluded
    # silently or auto-included unflagged.
    records = flag_engagement_anomalies(records)
    clean_records = [r for r in records if not r["engagement_anomaly_flag"]]
    flagged_records = [r for r in records if r["engagement_anomaly_flag"]]

    # Fail loudly here rather than writing a malformed row that T1.3 chokes on later.
    validated_records = [NormalizedPost.model_validate(record).model_dump() for record in clean_records]

    csv_path = store.save("linkedin", validated_records)
    jsonl_path = store.save_jsonl("linkedin", validated_records)

    try:
        snapshot = build_snapshot(validated_records)
        save_snapshot(snapshot)
    except ValueError:
        pass

    if flagged_records:
        validated_flagged = [
            NormalizedPost.model_validate(record).model_dump() for record in flagged_records
        ]
        flagged_path = store.save_jsonl("linkedin_flagged", validated_flagged)
        print(
            f"Held out {len(flagged_records)} post(s) with anomalous engagement ratios "
            f"for manual review: {flagged_path}"
        )

    return csv_path, jsonl_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-gemini",
        action="store_true",
        help="Also run Stage 2 (Gemini qualitative tags) — one API call per post.",
    )
    parser.add_argument(
        "--with-profile-enrichment",
        action="store_true",
        help=(
            "Merge a saved profile scrape onto raw posts for follower-normalized "
            "benchmarking + local posting time. Requires a saved "
            "linkedin_profiles_*.json from processors/run_sample_collection.py "
            "(or run_profile_enrichment.py for backfill) — fails clearly if none exists."
        ),
    )
    parser.add_argument(
        "--profile-file",
        default=None,
        help="Path to a specific profile scrape (defaults to the latest under data/raw/).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    csv_path, jsonl_path = run_pipeline(
        with_gemini=args.with_gemini,
        with_profile_enrichment=args.with_profile_enrichment,
        profile_file=args.profile_file,
    )
    print(f"Wrote {csv_path}")
    print(f"Wrote {jsonl_path}")
