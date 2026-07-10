"""Profile-only backfill CLI for existing post scans (legacy / repair path).

New collections should use processors/run_sample_collection.py, which runs
post search and profile enrichment together. This module remains for:
  - Old post-only scans created before unified collection
  - Re-running profile enrichment after a partial collection failure

Loads a raw post-scan JSON (data/raw/linkedin_*.json), classifies every
author as personal vs. business, scrapes personal authors via Apify, merges
follower data, and saves enriched CSV + profile JSON.

Usage:
    python -m processors.run_profile_enrichment
    python -m processors.run_profile_enrichment --raw-file data/raw/linkedin_20260703T162118Z.json
    python -m processors.run_profile_enrichment --limit 20
"""

import argparse
import glob
import json
from pathlib import Path
from typing import Any, Optional

from config.settings import Settings, load_settings
from processors.profile_sources import extract_scan_timestamp
from processors.run_sample_collection import run_profile_backfill
from storage.processed_store import ProcessedStore

_OUTPUT_FIELDS = (
    "post_id",
    "linkedin_url",
    "author_public_id",
    "author_name",
    "author_linkedin_url",
    "is_business",
    "follower_count",
    "connections_count",
    "headline",
    "location_text",
    "open_to_work",
    "hiring",
    "premium",
    "influencer",
    "verified",
)


def _latest_raw_scan(raw_data_dir: str) -> Path:
    """Return the most recent linkedin_*.json post scan (excludes profile scans)."""
    files = [
        Path(p)
        for p in sorted(glob.glob(f"{raw_data_dir}/linkedin_*.json"))
        if "profiles" not in Path(p).name
    ]
    if not files:
        raise ValueError(f"No raw post scan files found under {raw_data_dir}/linkedin_*.json")
    return files[-1]


def _flatten_for_csv(enriched_post: dict[str, Any]) -> dict[str, Any]:
    from processors.profile_enricher import clean_profile_url

    author = enriched_post.get("author") or {}
    flat = {
        "post_id": enriched_post.get("id") or "",
        "linkedin_url": enriched_post.get("linkedinUrl") or "",
        "author_public_id": author.get("publicIdentifier") or author.get("universalName") or "",
        "author_name": author.get("name") or "",
        "author_linkedin_url": clean_profile_url(author.get("linkedinUrl") or ""),
    }
    for field in _OUTPUT_FIELDS:
        if field not in flat:
            flat[field] = enriched_post.get(field)
    return flat


def run_profile_enrichment(
    raw_file: Optional[str] = None,
    settings: Optional[Settings] = None,
    store: Optional[ProcessedStore] = None,
    limit: Optional[int] = None,
) -> Path:
    """Enrich an existing post scan with author follower data. Returns enriched CSV path."""
    settings = settings or load_settings()
    store = store or ProcessedStore()

    raw_path = Path(raw_file) if raw_file else _latest_raw_scan(settings.raw_data_dir)
    posts = json.loads(raw_path.read_text())
    timestamp = extract_scan_timestamp(raw_path)

    result = run_profile_backfill(
        posts,
        settings=settings,
        profile_url_limit=limit,
        timestamp=timestamp,
    )

    personal_count = sum(1 for p in result.enriched_posts if not p.get("is_business"))
    business_count = sum(1 for p in result.enriched_posts if p.get("is_business"))
    print(
        f"Loaded {len(posts)} post(s) from {raw_path.name}: "
        f"{personal_count} personal-authored, {business_count} business-authored."
    )
    if result.profile_path:
        print(f"Saved profile scrape: {result.profile_path}")

    if result.enriched_path:
        return result.enriched_path

    flattened = [_flatten_for_csv(post) for post in result.enriched_posts]
    return store.save("linkedin_enriched", flattened, timestamp=timestamp or None)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-file",
        default=None,
        help="Path to a specific raw post scan (defaults to the latest under data/raw/).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only scrape the first N unique personal-profile authors (manual/cheap test run).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    out_path = run_profile_enrichment(raw_file=args.raw_file, limit=args.limit)
    print(f"Wrote {out_path}")
