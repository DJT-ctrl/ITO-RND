"""Scrape fresh LinkedIn posts and prepare them for prediction."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from config.paths import resolve_data_path, utc_artifact_stamp
from config.settings import Settings, load_settings
from processors.post_analyser import PostAnalyser
from processors.profile_enricher import enrich_posts_with_follower_data
from processors.run_sample_collection import _resolve_profile_records
from scrapers.linkedin_scraper import LinkedInScraper
from validation_pipeline.schemas import CollectedPost


def _parse_posted_at(post: dict[str, Any]) -> datetime | None:
    ts = (post.get("postedAt") or {}).get("timestamp")
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _is_eligible_post(
    post: dict[str, Any],
    *,
    min_post_age: timedelta,
    now: datetime,
) -> bool:
    post_id = post.get("id")
    content = (post.get("content") or "").strip()
    linkedin_url = post.get("linkedinUrl")
    posted_at = _parse_posted_at(post)
    if not post_id or not content or not linkedin_url or posted_at is None:
        return False
    age = now - posted_at
    return age >= min_post_age


def raw_posts_to_collected(
    enriched_posts: list[dict[str, Any]],
    settings: Settings,
    *,
    skip_min_age: bool = False,
) -> list[CollectedPost]:
    """Convert Apify post dicts (optionally profile-enriched) to CollectedPost rows."""
    analyser = PostAnalyser(settings)
    now = datetime.now(timezone.utc)
    min_age = timedelta(hours=settings.validation_min_post_age_hours)
    collected: list[CollectedPost] = []

    for post in enriched_posts:
        if not skip_min_age and not _is_eligible_post(post, min_post_age=min_age, now=now):
            continue
        posted_at = _parse_posted_at(post)
        if posted_at is None:
            continue
        content = (post.get("content") or "").strip()
        linkedin_url = post.get("linkedinUrl")
        post_id = post.get("id")
        if not post_id or not content or not linkedin_url:
            continue
        features = analyser.compute_python_features(post)
        author = post.get("author") or {}
        collected.append(
            CollectedPost(
                linkedin_post_id=str(post_id),
                linkedin_url=str(linkedin_url),
                author_public_id=str(author.get("publicIdentifier") or ""),
                content=content,
                posted_at=posted_at,
                follower_count=features.get("follower_count"),
                likes=int(features.get("likes") or 0),
                comments=int(features.get("comments") or 0),
                shares=int(features.get("shares") or 0),
                total_engagement=int(features.get("total_engagement") or 0),
            )
        )
    return collected


def collect_posts(
    search_params: dict[str, Any],
    *,
    settings: Settings | None = None,
    profile_url_limit: int | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> list[CollectedPost]:
    """Scrape posts, enrich profiles, and return analysis-ready records."""
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

    progress("Scraping posts...")
    scraper = LinkedInScraper(settings)
    scrape_result = scraper.fetch_samples(search_params, context="validation_collect")
    raw_posts = scrape_result.items
    progress(f"Found {len(raw_posts)} post(s).")

    progress("Scraping author profiles from posts...")
    apify_runs: list = []
    if scrape_result.run_record is not None:
        apify_runs.append(scrape_result.run_record)
    profile_records, urls_scraped, fresh_records = _resolve_profile_records(
        raw_posts,
        settings,
        use_profile_cache=False,
        profile_url_limit=profile_url_limit,
        apify_runs=apify_runs,
        context="validation_collect",
    )
    if urls_scraped:
        progress(f"Scraped {len(fresh_records)} author profile(s).")
    else:
        progress("No personal authors to scrape (company pages use free follower counts).")
    enriched_posts = enrich_posts_with_follower_data(raw_posts, profile_records)

    timestamp = utc_artifact_stamp()
    _save_collect_artifact(settings, enriched_posts, timestamp)

    collected = raw_posts_to_collected(enriched_posts, settings, skip_min_age=False)
    progress(f"Collected {len(collected)} eligible post(s) from {len(enriched_posts)} scraped.")
    return collected


def _save_collect_artifact(
    settings: Settings,
    posts: list[dict[str, Any]],
    timestamp: str,
) -> Path:
    out_dir = resolve_data_path(settings.validation_data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"collect_{timestamp}.json"
    path.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
