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
from processors.profile_enricher import enrich_posts_with_follower_data
from processors.profile_sources import load_profile_records
from processors.run_db_ingest import run_db_ingest
from processors.run_pipeline import load_raw_posts, run_pipeline
from processors.run_sample_collection import (
    _harvestapi_from_cache,
    _merge_profile_records,
    _resolve_profile_records,
    _unique_personal_author_ids,
)
from storage.profile_store import (
    get_profile,
    is_profile_stale,
    sync_profiles_from_enriched_posts,
)
from storage.vector_store import create_schema, get_connection


def _load_disk_profile_records(
    settings: Settings, profile_file: Optional[str]
) -> list[dict[str, Any]]:
    if profile_file:
        return load_profile_records(profile_file, settings.raw_data_dir)
    candidates = sorted(glob.glob(f"{settings.raw_data_dir}/linkedin_profiles_*.json"))
    if candidates:
        return json.loads(Path(candidates[-1]).read_text())
    return []


def _cached_records_from_db(
    conn,
    posts: list[dict[str, Any]],
    *,
    staleness_days: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for author_id in _unique_personal_author_ids(posts):
        cached = get_profile(conn, author_id)
        if is_profile_stale(cached, staleness_days=staleness_days):
            continue
        if cached and cached.get("follower_count") is not None:
            records.append(_harvestapi_from_cache(cached))
    return records


def _save_profile_scrape(raw_data_dir: str, records: list[dict[str, Any]]) -> Path:
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = Path(raw_data_dir) / f"linkedin_profiles_{timestamp}.json"
    path.write_text(json.dumps(records, indent=2))
    return path


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

    disk_records = _load_disk_profile_records(settings, profile_file) if (
        profile_file or skip_scrape
    ) else []

    if skip_scrape:
        profile_records = list(disk_records)
        if settings.database_url:
            conn = get_connection(settings)
            try:
                create_schema(conn)
                cached = _cached_records_from_db(
                    conn,
                    raw_posts,
                    staleness_days=settings.profile_cache_staleness_days,
                )
                profile_records = _merge_profile_records(profile_records, cached)
                enriched_for_cache = enrich_posts_with_follower_data(
                    raw_posts, profile_records
                )
                sync_profiles_from_enriched_posts(conn, enriched_for_cache)
            finally:
                conn.close()
    else:
        resolved, _, _ = _resolve_profile_records(
            raw_posts,
            settings,
            use_profile_cache=bool(settings.database_url),
            profile_url_limit=None,
        )
        profile_records = (
            _merge_profile_records(disk_records, resolved) if disk_records else resolved
        )

        if settings.database_url:
            conn = get_connection(settings)
            try:
                create_schema(conn)
                enriched_for_cache = enrich_posts_with_follower_data(
                    raw_posts, profile_records
                )
                sync_profiles_from_enriched_posts(conn, enriched_for_cache)
            finally:
                conn.close()

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
