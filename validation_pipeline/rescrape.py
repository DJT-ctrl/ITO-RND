"""Re-scrape engagement for tracked predictions via direct post URLs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from config.paths import resolve_data_path, utc_artifact_stamp
from config.settings import Settings
from scrapers.linkedin_post_url_scraper import LinkedInPostUrlScraper
from validation_pipeline.schemas import CollectedPost, EngagementActuals, PredictionRecord


def _post_id_candidates(item: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("id", "entityId"):
        value = item.get(key)
        if value is not None and str(value).strip():
            ids.add(str(value))
    engagement = item.get("engagement") or {}
    engagement_id = engagement.get("id")
    if engagement_id is not None and str(engagement_id).strip():
        ids.add(str(engagement_id))
    return ids


def match_post_in_results(
    items: list[dict[str, Any]],
    prediction: PredictionRecord,
) -> dict[str, Any] | None:
    """Find the tracked post in a scraper result set by id or URL."""
    target_id = str(prediction.linkedin_post_id)
    target_url = _normalize_post_url(prediction.linkedin_url)
    for item in items:
        if target_id in _post_id_candidates(item):
            return item
        item_url = item.get("linkedinUrl")
        if item_url and _normalize_post_url(str(item_url)) == target_url:
            return item
    return None


def _author_profile_url(author_public_id: str) -> str | None:
    public_id = (author_public_id or "").strip()
    if not public_id:
        return None
    return f"https://www.linkedin.com/in/{public_id}"


def _normalize_post_url(url: str) -> str:
    return url.split("?")[0].rstrip("/")


def extract_engagement(post: dict[str, Any]) -> EngagementActuals:
    engagement = post.get("engagement") or {}
    likes = int(engagement.get("likes") or 0)
    comments = int(engagement.get("comments") or 0)
    shares = int(engagement.get("shares") or 0)
    return EngagementActuals(
        likes=likes,
        comments=comments,
        shares=shares,
        total_engagement=likes + comments + shares,
    )


def _save_rescrape_artifact(
    settings: Settings,
    items: list[dict[str, Any]],
    label: str,
) -> Path:
    out_dir = resolve_data_path(settings.validation_data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"rescrape_{label}_{utc_artifact_stamp()}.json"
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def fetch_engagement_by_urls(
    predictions: list[PredictionRecord],
    settings: Settings,
    *,
    scraper: Optional[LinkedInPostUrlScraper] = None,
    context: str = "validation_rescrape",
) -> dict[UUID, EngagementActuals]:
    """Batch re-scrape posts by LinkedIn URL; one Apify run for the whole set."""
    if not predictions:
        return {}

    scraper = scraper or LinkedInPostUrlScraper(settings)
    url_by_prediction = {
        p.prediction_id: p.linkedin_url.strip()
        for p in predictions
        if p.linkedin_url and p.linkedin_url.strip()
    }
    unique_urls = list(dict.fromkeys(url_by_prediction.values()))
    result = scraper.fetch_posts_by_urls(unique_urls, context=context)
    _save_rescrape_artifact(settings, result.items, context.replace(":", "_"))

    url_to_items: dict[str, list[dict[str, Any]]] = {}
    for item in result.items:
        raw_url = item.get("linkedinUrl")
        if not raw_url:
            continue
        key = _normalize_post_url(str(raw_url))
        url_to_items.setdefault(key, []).append(item)

    actuals: dict[UUID, EngagementActuals] = {}
    missing: list[PredictionRecord] = []
    for prediction in predictions:
        matched = match_post_in_results(result.items, prediction)
        if matched is not None:
            actuals[prediction.prediction_id] = extract_engagement(matched)
        else:
            missing.append(prediction)

    for prediction in missing:
        single = scraper.fetch_posts_by_urls(
            [prediction.linkedin_url],
            context=f"{context}:{prediction.prediction_id}",
        )
        matched = match_post_in_results(single.items, prediction)
        if matched is None:
            profile_url = _author_profile_url(prediction.author_public_id)
            if profile_url:
                profile_result = scraper.fetch_posts_by_urls(
                    [profile_url],
                    max_posts=settings.validation_rescrape_profile_max_posts,
                    context=f"{context}:{prediction.prediction_id}:profile",
                )
                matched = match_post_in_results(profile_result.items, prediction)
        if matched is not None:
            actuals[prediction.prediction_id] = extract_engagement(matched)

    return actuals


def fetch_engagement(
    prediction: PredictionRecord,
    settings: Settings,
    *,
    scraper: Optional[LinkedInPostUrlScraper] = None,
) -> EngagementActuals:
    """Re-scrape one post by URL and return updated engagement."""
    actuals_map = fetch_engagement_by_urls(
        [prediction],
        settings,
        scraper=scraper,
        context=f"validation_rescrape:{prediction.prediction_id}",
    )
    actuals = actuals_map.get(prediction.prediction_id)
    if actuals is None:
        raise ValueError(
            f"Could not re-match post {prediction.linkedin_post_id} "
            f"({prediction.linkedin_url}): Apify returned no matching post "
            f"after direct URL scrape and author profile fallback "
            f"(up to {settings.validation_rescrape_profile_max_posts} recent posts). "
            f"The post may be deleted, private, or no longer on the public profile."
        )
    return actuals


def prediction_to_collected(post: PredictionRecord) -> CollectedPost:
    return CollectedPost(
        linkedin_post_id=post.linkedin_post_id,
        linkedin_url=post.linkedin_url,
        author_public_id=post.author_public_id,
        content=post.content,
        posted_at=post.posted_at,
        likes=post.actual_likes or 0,
        comments=post.actual_comments or 0,
        shares=post.actual_shares or 0,
        total_engagement=post.actual_total_engagement or 0,
    )
