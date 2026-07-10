"""Unified sample collection: post search + author profile enrichment (Step 1).

Runs both scrapers back-to-back on every new collection:
  1. LinkedIn post search (Apify post-search actor)
  2. Personal-author profile scrape (Apify profile actor) + merge

Saves paired artifacts under a shared timestamp:
  - data/raw/linkedin_{ts}.json
  - data/raw/linkedin_profiles_{ts}.json  (only when personal authors were scraped)
  - data/processed/linkedin_enriched_{ts}.csv

Usage:
    python -m processors.run_sample_collection --search "ai marketing" --max-posts 20
    python -m processors.run_sample_collection --search "ai marketing" --profile-limit 5
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from config.settings import Settings, load_settings
from config.paths import utc_artifact_stamp
from processors.profile_enricher import (
    clean_profile_url,
    collect_personal_profile_urls,
    enrich_posts_with_follower_data,
)
from scrapers.linkedin_profile_scraper import LinkedInProfileScraper
from scrapers.linkedin_scraper import LinkedInScraper
from storage.processed_store import ProcessedStore
from storage.profile_store import (
    get_profile,
    is_profile_stale,
    profile_record_from_harvestapi,
    sync_profiles_from_enriched_posts,
    upsert_profile,
)
from storage.sample_store import SampleStore
from storage.vector_store import create_schema, get_connection

_ENRICHED_CSV_FIELDS = (
    "post_id",
    "author_name",
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


@dataclass
class CollectionResult:
    post_path: Path
    profile_path: Path | None
    enriched_path: Path | None
    posts: list[dict[str, Any]]
    profile_records: list[dict[str, Any]]
    enriched_posts: list[dict[str, Any]]
    timestamp: str


def _utc_timestamp() -> str:
    return utc_artifact_stamp()


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
    urls: set[str] = set()
    for post in posts:
        author = post.get("author") or {}
        if author.get("publicIdentifier") not in author_ids:
            continue
        url = author.get("linkedinUrl") or ""
        if url:
            urls.add(clean_profile_url(url))
    return sorted(urls)


def _harvestapi_from_cache(profile: dict[str, Any]) -> dict[str, Any]:
    """Minimal harvestapi-shaped record from a profiles-table cache row."""
    location_text = profile.get("location_text")
    return {
        "publicIdentifier": profile.get("author_public_id"),
        "followerCount": profile.get("follower_count"),
        "connectionsCount": profile.get("connections_count"),
        "headline": profile.get("headline"),
        "location": {"linkedinText": location_text} if location_text else {},
        "linkedinUrl": profile.get("linkedin_url"),
    }


def _merge_profile_records(
    existing: list[dict[str, Any]], fresh: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {
        record.get("publicIdentifier"): record
        for record in existing
        if record.get("publicIdentifier")
    }
    for record in fresh:
        public_id = record.get("publicIdentifier")
        if public_id:
            by_id[public_id] = record
    return list(by_id.values())


def _flatten_enriched_for_csv(enriched_post: dict[str, Any]) -> dict[str, Any]:
    author = enriched_post.get("author") or {}
    row = {
        "post_id": enriched_post.get("id") or "",
        "author_name": author.get("name") or "",
    }
    for field in _ENRICHED_CSV_FIELDS:
        if field not in row:
            row[field] = enriched_post.get(field)
    return row


def _resolve_profile_records(
    posts: list[dict[str, Any]],
    settings: Settings,
    *,
    use_profile_cache: bool,
    profile_url_limit: int | None,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """Return (profile_records, urls_to_scrape, fresh_scrape_records)."""
    personal_urls = collect_personal_profile_urls(posts)
    if profile_url_limit is not None:
        personal_urls = personal_urls[:profile_url_limit]

    cached_records: list[dict[str, Any]] = []
    urls_to_scrape = list(personal_urls)

    if use_profile_cache and settings.database_url:
        conn = get_connection(settings)
        try:
            create_schema(conn)
            personal_ids = _unique_personal_author_ids(posts)
            stale_ids: set[str] = set()
            for author_id in personal_ids:
                cached = get_profile(conn, author_id)
                if is_profile_stale(
                    cached, staleness_days=settings.profile_cache_staleness_days
                ):
                    stale_ids.add(author_id)
                elif cached and cached.get("follower_count") is not None:
                    cached_records.append(_harvestapi_from_cache(cached))

            if stale_ids:
                urls_to_scrape = _urls_for_author_ids(posts, stale_ids)
                if profile_url_limit is not None:
                    urls_to_scrape = urls_to_scrape[:profile_url_limit]
            else:
                urls_to_scrape = []
        finally:
            conn.close()

    fresh_records: list[dict[str, Any]] = []
    if urls_to_scrape:
        scraper = LinkedInProfileScraper(settings)
        fresh_records = scraper.fetch_samples({"profileUrls": urls_to_scrape})

        if use_profile_cache and settings.database_url:
            conn = get_connection(settings)
            try:
                create_schema(conn)
                for record in fresh_records:
                    row = profile_record_from_harvestapi(record)
                    if row:
                        upsert_profile(conn, row)
            finally:
                conn.close()

    profile_records = _merge_profile_records(cached_records, fresh_records)
    return profile_records, urls_to_scrape, fresh_records


def run_sample_collection(
    search_params: dict[str, Any],
    *,
    settings: Settings | None = None,
    profile_url_limit: int | None = None,
    use_profile_cache: bool = True,
    on_progress: Callable[[str], None] | None = None,
) -> CollectionResult:
    """Run post search then profile enrichment; return paths and merged data."""
    settings = settings or load_settings()
    if not settings.apify_api_token:
        raise ValueError("APIFY_API_TOKEN is not set (check your .env file).")
    if not settings.apify_actor_id:
        raise ValueError("APIFY_ACTOR_ID is not set (check your .env file).")
    if not settings.apify_profile_actor_id:
        raise ValueError("APIFY_PROFILE_ACTOR_ID is not set (check your .env file).")

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    timestamp = _utc_timestamp()
    store = SampleStore(settings.raw_data_dir)
    processed_store = ProcessedStore()

    progress("Phase 1/2: Searching posts...")
    post_scraper = LinkedInScraper(settings)
    posts = post_scraper.fetch_samples(search_params)
    post_path = store.save("linkedin", posts, timestamp=timestamp)

    progress("Phase 2/2: Enriching author profiles...")
    profile_records, urls_scraped, fresh_records = _resolve_profile_records(
        posts,
        settings,
        use_profile_cache=use_profile_cache,
        profile_url_limit=profile_url_limit,
    )

    profile_path: Path | None = None
    if fresh_records:
        profile_path = store.save("linkedin_profiles", fresh_records, timestamp=timestamp)
    elif profile_records and not fresh_records:
        # Cache-only path: still persist merged records for downstream pairing.
        profile_path = store.save("linkedin_profiles", profile_records, timestamp=timestamp)

    if urls_scraped:
        progress(f"Phase 2/2: Scraped {len(fresh_records)} author profile(s).")
    elif collect_personal_profile_urls(posts):
        progress("Phase 2/2: Personal authors satisfied from cache — no paid scrape.")
    else:
        progress("Phase 2/2: No personal authors — business follower counts only.")

    enriched_posts = enrich_posts_with_follower_data(posts, profile_records)

    if settings.database_url:
        conn = get_connection(settings)
        try:
            create_schema(conn)
            sync_profiles_from_enriched_posts(conn, enriched_posts)
        finally:
            conn.close()

    enriched_path: Path | None = None
    flattened = [_flatten_enriched_for_csv(post) for post in enriched_posts]
    if flattened:
        enriched_path = processed_store.save(
            "linkedin_enriched", flattened, timestamp=timestamp
        )

    return CollectionResult(
        post_path=post_path,
        profile_path=profile_path,
        enriched_path=enriched_path,
        posts=posts,
        profile_records=profile_records,
        enriched_posts=enriched_posts,
        timestamp=timestamp,
    )


def run_profile_backfill(
    posts: list[dict[str, Any]],
    *,
    settings: Settings | None = None,
    profile_url_limit: int | None = None,
    use_profile_cache: bool = True,
    timestamp: str | None = None,
) -> CollectionResult:
    """Profile-only enrichment for an existing post scan (no post search)."""
    settings = settings or load_settings()
    if not settings.apify_profile_actor_id:
        raise ValueError("APIFY_PROFILE_ACTOR_ID is not set (check your .env file).")

    timestamp = timestamp or _utc_timestamp()
    store = SampleStore(settings.raw_data_dir)
    processed_store = ProcessedStore()

    profile_records, _, fresh_records = _resolve_profile_records(
        posts,
        settings,
        use_profile_cache=use_profile_cache,
        profile_url_limit=profile_url_limit,
    )

    profile_path: Path | None = None
    if fresh_records:
        profile_path = store.save("linkedin_profiles", fresh_records, timestamp=timestamp)
    elif profile_records:
        profile_path = store.save("linkedin_profiles", profile_records, timestamp=timestamp)

    enriched_posts = enrich_posts_with_follower_data(posts, profile_records)

    if settings.database_url:
        conn = get_connection(settings)
        try:
            create_schema(conn)
            sync_profiles_from_enriched_posts(conn, enriched_posts)
        finally:
            conn.close()

    enriched_path: Path | None = None
    flattened = [_flatten_enriched_for_csv(post) for post in enriched_posts]
    if flattened:
        enriched_path = processed_store.save(
            "linkedin_enriched", flattened, timestamp=timestamp
        )

    return CollectionResult(
        post_path=Path(),
        profile_path=profile_path,
        enriched_path=enriched_path,
        posts=posts,
        profile_records=profile_records,
        enriched_posts=enriched_posts,
        timestamp=timestamp,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--search",
        default="ai marketing",
        help="LinkedIn search query (default: ai marketing).",
    )
    parser.add_argument(
        "--max-posts",
        type=int,
        default=None,
        help="Max posts to fetch (defaults to Settings.default_search_limit).",
    )
    parser.add_argument(
        "--sort-by",
        default="relevance",
        choices=["relevance", "date"],
        help="Sort order for post search.",
    )
    parser.add_argument(
        "--posted-limit",
        default="all",
        help="Time filter: all, 1h, 24h, week, month, 3months, 6months, year.",
    )
    parser.add_argument(
        "--profile-limit",
        type=int,
        default=None,
        help="Cap personal profile URLs sent to the paid scraper (cheap test runs).",
    )
    parser.add_argument(
        "--no-profile-cache",
        action="store_true",
        help="Always scrape personal authors; ignore the profiles DB cache.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    settings = load_settings()
    params: dict[str, Any] = {
        "searchQueries": [args.search],
        "maxPosts": args.max_posts or settings.default_search_limit,
        "sortBy": args.sort_by,
    }
    if args.posted_limit != "all":
        params["postedLimit"] = args.posted_limit

    result = run_sample_collection(
        params,
        settings=settings,
        profile_url_limit=args.profile_limit,
        use_profile_cache=not args.no_profile_cache,
        on_progress=print,
    )
    print(f"Posts: {result.post_path}")
    if result.profile_path:
        print(f"Profiles: {result.profile_path}")
    if result.enriched_path:
        print(f"Enriched CSV: {result.enriched_path}")
