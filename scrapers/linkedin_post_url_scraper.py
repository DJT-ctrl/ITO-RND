"""Scrape LinkedIn posts directly by post URL (validation re-scrape).

Uses harvestapi/linkedin-profile-posts, which accepts post URLs in
``targetUrls`` (not just profile URLs). One actor run can batch many URLs.
"""

from __future__ import annotations

from typing import Any, Optional

from apify_client import ApifyClient

from config.settings import Settings
from scrapers.base_scraper import BaseScraper
from scrapers.result import ScrapeResult
from telemetry.apify import apify_run_record_from_response, save_apify_run


class LinkedInPostUrlScraper(BaseScraper):
    platform_name = "linkedin_post_urls"

    def __init__(self, settings: Settings, client: Optional[ApifyClient] = None):
        if not settings.apify_api_token:
            raise ValueError("APIFY_API_TOKEN is not set (check your .env file).")
        if not settings.apify_post_url_actor_id:
            raise ValueError("APIFY_POST_URL_ACTOR_ID is not set (check your .env file).")

        self._settings = settings
        self._client = client or ApifyClient(settings.apify_api_token)

    def fetch_samples(
        self,
        params: dict[str, Any],
        *,
        context: Optional[str] = None,
        persist_telemetry: bool = True,
    ) -> ScrapeResult:
        """Fetch posts by URL list (``targetUrls`` or ``urls`` in params)."""
        urls = params.get("targetUrls") or params.get("urls") or []
        return self.fetch_posts_by_urls(
            list(urls),
            context=context,
            persist_telemetry=persist_telemetry,
        )

    def fetch_posts_by_urls(
        self,
        urls: list[str],
        *,
        max_posts: int = 1,
        context: Optional[str] = None,
        persist_telemetry: bool = True,
    ) -> ScrapeResult:
        """Fetch posts for a list of LinkedIn post or profile URLs in one Apify run."""
        cleaned = [u.strip() for u in urls if u and u.strip()]
        if not cleaned:
            return ScrapeResult(items=[], run_record=None)

        params: dict[str, Any] = {
            "targetUrls": cleaned,
            "maxPosts": max(1, max_posts),
            "includeQuotePosts": False,
            "includeReposts": False,
        }
        run = self._client.actor(self._settings.apify_post_url_actor_id).call(run_input=params)
        dataset_id = run["defaultDatasetId"]
        items = self._client.dataset(dataset_id).list_items().items
        record = apify_run_record_from_response(
            run,
            actor_id=self._settings.apify_post_url_actor_id,
            scraper="linkedin_posts",
            item_count=len(items),
            context=context,
        )
        if persist_telemetry:
            save_apify_run(record, self._settings)
        return ScrapeResult(items=items, run_record=record)
