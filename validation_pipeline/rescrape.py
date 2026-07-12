"""Re-scrape engagement for a tracked prediction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from config.paths import resolve_data_path, utc_artifact_stamp
from config.settings import Settings
from scrapers.linkedin_scraper import LinkedInScraper
from validation_pipeline.schemas import CollectedPost, EngagementActuals, PredictionRecord


def _content_search_query(content: str, max_len: int = 85) -> str:
    cleaned = " ".join(content.split())
    return cleaned[:max_len] if cleaned else "linkedin post"


def build_rescrape_params(prediction: PredictionRecord) -> dict[str, Any]:
    """Build Apify post-search params to re-fetch a single tracked post."""
    params: dict[str, Any] = {
        "searchQueries": [_content_search_query(prediction.content)],
        "postedLimit": "week",
        "sortBy": "date",
        "maxPosts": 30,
    }
    if prediction.author_public_id:
        params["authorsPublicIdentifiers"] = [prediction.author_public_id]
    return params


def match_post_in_results(
    items: list[dict[str, Any]],
    prediction: PredictionRecord,
) -> dict[str, Any] | None:
    """Find the tracked post in a scraper result set by id or URL."""
    target_id = str(prediction.linkedin_post_id)
    target_url = prediction.linkedin_url
    for item in items:
        if str(item.get("id")) == target_id:
            return item
        if item.get("linkedinUrl") == target_url:
            return item
    return None


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
    prediction_id: str,
) -> Path:
    out_dir = resolve_data_path(settings.validation_data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"rescrape_{prediction_id}_{utc_artifact_stamp()}.json"
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def fetch_engagement(
    prediction: PredictionRecord,
    settings: Settings,
    *,
    scraper: Optional[LinkedInScraper] = None,
) -> EngagementActuals:
    """Re-scrape LinkedIn and return updated engagement for a tracked post."""
    scraper = scraper or LinkedInScraper(settings)
    params = build_rescrape_params(prediction)
    primary = scraper.fetch_samples(
        params,
        context=f"validation_rescrape:{prediction.prediction_id}",
    )
    items = primary.items
    _save_rescrape_artifact(settings, items, str(prediction.prediction_id))

    matched = match_post_in_results(items, prediction)
    if matched is None and prediction.author_public_id:
        fallback_params = {
            "searchQueries": [_content_search_query(prediction.content)],
            "authorsPublicIdentifiers": [prediction.author_public_id],
            "postedLimit": "month",
            "sortBy": "date",
            "maxPosts": 50,
        }
        fallback = scraper.fetch_samples(
            fallback_params,
            context=f"validation_rescrape_fallback:{prediction.prediction_id}",
        )
        items = fallback.items
        _save_rescrape_artifact(settings, items, f"{prediction.prediction_id}_fallback")
        matched = match_post_in_results(items, prediction)

    if matched is None:
        raise ValueError(
            f"Could not re-match post {prediction.linkedin_post_id} "
            f"({prediction.linkedin_url}) in scraper results."
        )
    return extract_engagement(matched)


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
