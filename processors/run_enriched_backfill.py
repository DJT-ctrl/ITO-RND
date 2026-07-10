"""Backfill + enriched pipeline runner (T6 Point 1).

Orchestrates the full reach-normalization path:
  1. Load raw post scans
  2. Use the profiles cache where fresh; scrape only stale/missing personal authors
  3. Sync follower counts into the profiles table
  4. Save a profile scrape JSON for run_pipeline --with-profile-enrichment
  5. Run T1.2 with audience-adjusted benchmarks
  6. Optionally re-ingest into Postgres when DATABASE_URL is set

Usage:
    python -m processors.run_enriched_backfill
    python -m processors.run_enriched_backfill --skip-scrape   # cache + business authors only
    python -m processors.run_enriched_backfill --with-db-ingest
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Any, Optional

from config.settings import Settings, load_settings
from processors.profile_enricher import (
    collect_personal_profile_urls,
    enrich_posts_with_follower_data,
)
from processors.profile_sources import load_profile_records
from processors.run_db_ingest import run_db_ingest
from processors.run_pipeline import load_raw_posts, run_pipeline
from scrapers.linkedin_profile_scraper import LinkedInProfileScraper
from storage.profile_store import (
    get_profile,
    is_profile_stale,
    profile_record_from_harvestapi,
    sync_profiles_from_enriched_posts,
    upsert_profile,
)
from storage.vector_store import create_schema, get_connection


def _unique_personal_author_ids(posts: list[dict[str, Any]]) -> list[str]:
    ids: set[str] = set()
    for post in posts:
        author = post.get("author") or {}
        if author.get("type") == "company":
            continue
        public_id = author.get("publicIdentifier")
        if public_id:
            ids.add(public_id)
    return sorted(ids)


def _urls_for_author_ids(posts: list[dict[str, Any]], author_ids: set[str]) -> list[str]:
    from processors.profile_enricher import clean_profile_url

    urls: set[str] = set()
    for post in posts:
        author = post.get("author") or {}
        if author.get("publicIdentifier") not in author_ids:
            continue
        url = author.get("linkedinUrl") or ""
        if url:
            urls.add(clean_profile_url(url))
    return sorted(urls)


def _save_profile_scrape(raw_data_dir: str, records: list[dict[str, Any]]) -> Path:
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = Path(raw_data_dir) / f"linkedin_profiles_{timestamp}.json"
    path.write_text(json.dumps(records, indent=2))
    return path


def _merge_profile_records(
    existing: list[dict[str, Any]], fresh: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {record.get("publicIdentifier"): record for record in existing if record.get("publicIdentifier")}
    for record in fresh:
        public_id = record.get("publicIdentifier")
        if public_id:
            by_id[public_id] = record
    return list(by_id.values())


def run_enriched_backfill(
    settings: Optional[Settings] = None,
    *,
    skip_scrape: bool = False,
    with_db_ingest: bool = False,
    profile_file: Optional[str] = None,
) -> tuple[Path, Path]:
    """Run profile enrichment backfill and the enriched T1.2 pipeline.

    Returns (csv_path, jsonl_path) from run_pipeline.
    """
    settings = settings or load_settings()
    raw_posts = load_raw_posts(settings.raw_data_dir)
    if not raw_posts:
        raise ValueError(f"No raw posts found under {settings.raw_data_dir}/linkedin_*.json")

    profile_records: list[dict[str, Any]] = []
    if profile_file:
        profile_records = load_profile_records(profile_file, settings.raw_data_dir)
    else:
        candidates = sorted(glob.glob(f"{settings.raw_data_dir}/linkedin_profiles_*.json"))
        if candidates:
            profile_records = json.loads(Path(candidates[-1]).read_text())

    if settings.database_url:
        conn = get_connection(settings)
        try:
            create_schema(conn)
            personal_ids = _unique_personal_author_ids(raw_posts)
            stale_ids: set[str] = set()
            for author_id in personal_ids:
                cached = get_profile(conn, author_id)
                if is_profile_stale(
                    cached, staleness_days=settings.profile_cache_staleness_days
                ):
                    stale_ids.add(author_id)

            if not skip_scrape and stale_ids:
                urls = _urls_for_author_ids(raw_posts, stale_ids)
                if urls:
                    scraper = LinkedInProfileScraper(settings)
                    fresh_records = scraper.fetch_samples({"profileUrls": urls})
                    profile_records = _merge_profile_records(profile_records, fresh_records)
                    for record in fresh_records:
                        row = profile_record_from_harvestapi(record)
                        if row:
                            upsert_profile(conn, row)

            enriched_for_cache = enrich_posts_with_follower_data(raw_posts, profile_records)
            sync_profiles_from_enriched_posts(conn, enriched_for_cache)
        finally:
            conn.close()
    elif not skip_scrape:
        personal_urls = collect_personal_profile_urls(raw_posts)
        if personal_urls:
            scraper = LinkedInProfileScraper(settings)
            fresh_records = scraper.fetch_samples({"profileUrls": personal_urls})
            profile_records = _merge_profile_records(profile_records, fresh_records)

    if not profile_records and not skip_scrape:
        personal_urls = collect_personal_profile_urls(raw_posts)
        if personal_urls:
            scraper = LinkedInProfileScraper(settings)
            profile_records = scraper.fetch_samples({"profileUrls": personal_urls})

    if profile_records:
        saved_profile_path = _save_profile_scrape(settings.raw_data_dir, profile_records)
        print(f"Saved profile scrape: {saved_profile_path}")
    elif profile_file:
        saved_profile_path = Path(profile_file)
    elif skip_scrape:
        saved_profile_path = _save_profile_scrape(settings.raw_data_dir, [])
        print(f"No profile records on disk — using empty scrape file: {saved_profile_path}")
    else:
        raise ValueError(
            "No profile records available. Run a profile scrape first, pass --profile-file, "
            "or omit --skip-scrape when API credentials are configured."
        )

    csv_path, jsonl_path = run_pipeline(
        with_profile_enrichment=True,
        settings=settings,
        profile_file=str(saved_profile_path),
    )

    if with_db_ingest:
        if not settings.database_url:
            raise ValueError("--with-db-ingest requires DATABASE_URL to be set.")
        count = run_db_ingest(processed_file=str(jsonl_path), settings=settings)
        print(f"DB ingest complete: {count} row(s) upserted.")

    matched = sum(
        1
        for line in jsonl_path.read_text().splitlines()
        if json.loads(line).get("audience_adjusted_percentile") is not None
    )
    total = len(jsonl_path.read_text().splitlines())
    print(
        f"Enriched pipeline complete: {matched}/{total} post(s) have audience-adjusted benchmarks."
    )
    return csv_path, jsonl_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        help="Use existing profile scrape + business-author free counts only; do not call Apify.",
    )
    parser.add_argument(
        "--with-db-ingest",
        action="store_true",
        help="After pipeline, upsert enriched records into Postgres (requires DATABASE_URL).",
    )
    parser.add_argument(
        "--profile-file",
        default=None,
        help="Use a specific saved profile scrape JSON instead of discovering the latest.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    csv_path, jsonl_path = run_enriched_backfill(
        skip_scrape=args.skip_scrape,
        with_db_ingest=args.with_db_ingest,
        profile_file=args.profile_file,
    )
    print(f"Wrote {csv_path} and {jsonl_path}")
