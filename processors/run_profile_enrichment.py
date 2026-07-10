"""Standalone CLI for T6 Point 1's author follower enrichment.

Loads a raw post-scan JSON (data/raw/linkedin_*.json), classifies every
author as personal vs. business (processors/profile_enricher.py), scrapes
ONLY the personal-profile authors via the harvestapi/linkedin-profile-scraper
actor (business authors' follower counts come free from data already
scraped — no wasted credits), merges everything together, and saves ONE
enriched CSV with a row per post.

When DATABASE_URL is set, fresh follower counts are also upserted into the
``profiles`` scrape cache (storage/profile_store.py). For the full enriched
T1.2 + optional DB ingest path, use processors/run_enriched_backfill.py.

Usage:
    python -m processors.run_profile_enrichment
    python -m processors.run_profile_enrichment --raw-file data/raw/linkedin_20260703T162118Z.json
    python -m processors.run_profile_enrichment --limit 20   # cheap manual test run
"""

import argparse
import glob
import json
from pathlib import Path
from typing import Any, Optional

from config.settings import Settings, load_settings
from processors.profile_enricher import (
    clean_profile_url,
    collect_personal_profile_urls,
    enrich_posts_with_follower_data,
)
from scrapers.linkedin_profile_scraper import LinkedInProfileScraper
from storage.processed_store import ProcessedStore
from storage.profile_store import sync_profiles_from_enriched_posts
from storage.vector_store import create_schema, get_connection

# Only these flat fields are kept in the output CSV — the raw post JSON's
# nested author/engagement/postedAt/job/socialContent/comments objects are
# dropped entirely (unneeded for follower enrichment, and CSV can't
# represent them cleanly anyway).
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
    """Strip an enriched (raw JSON + merged fields) post down to the flat,
    CSV-friendly output columns — dropping the bulky nested raw JSON.
    """
    author = enriched_post.get("author") or {}
    flat = {
        "post_id": enriched_post.get("id") or "",
        "linkedin_url": enriched_post.get("linkedinUrl") or "",
        # Business authors' publicIdentifier is null — universalName is
        # their stable identifier instead (confirmed against real data).
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
    """Load a raw post scan, enrich every post with author follower data,
    and save one flattened CSV (one row per post). Returns the saved path.

    ``limit`` caps how many personal-profile URLs are sent to the paid
    scraper — useful for a cheap manual test run before enriching an
    entire dataset. ``None`` (default) scrapes every personal author found.
    """
    settings = settings or load_settings()
    store = store or ProcessedStore()

    raw_path = Path(raw_file) if raw_file else _latest_raw_scan(settings.raw_data_dir)
    posts = json.loads(raw_path.read_text())

    personal_urls = collect_personal_profile_urls(posts)
    if limit is not None:
        personal_urls = personal_urls[:limit]

    profile_records: list[dict] = []
    if personal_urls:
        scraper = LinkedInProfileScraper(settings)
        profile_records = scraper.fetch_samples({"profileUrls": personal_urls})

    enriched = enrich_posts_with_follower_data(posts, profile_records)
    business_count = sum(1 for p in enriched if p["is_business"])
    print(
        f"Loaded {len(posts)} post(s) from {raw_path.name}: "
        f"{len(personal_urls)} unique personal author(s) scraped, "
        f"{business_count} business-authored post(s) enriched for free "
        "(no extra scraper credits)."
    )

    if settings.database_url:
        conn = get_connection(settings)
        try:
            create_schema(conn)
            synced = sync_profiles_from_enriched_posts(conn, enriched)
            print(f"Synced {synced} author profile(s) to the profiles cache.")
        finally:
            conn.close()

    flattened = [_flatten_for_csv(post) for post in enriched]
    return store.save("linkedin_enriched", flattened)


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
