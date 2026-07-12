"""LinkedIn sample scraper, backed by a configurable Apify actor.

The actor ID lives in config (not hardcoded here), so pointing this class at
a different LinkedIn actor - e.g. swapping a keyword/hashtag search actor for
a company-page actor - never requires touching this class's logic.
"""

from typing import Any, Optional

from apify_client import ApifyClient

from config.settings import Settings
from scrapers.base_scraper import BaseScraper
from scrapers.result import ScrapeResult
from telemetry.apify import apify_run_record_from_response, save_apify_run


class LinkedInScraper(BaseScraper):
    platform_name = "linkedin"

    def __init__(self, settings: Settings, client: Optional[ApifyClient] = None):
        if not settings.apify_api_token:
            raise ValueError("APIFY_API_TOKEN is not set (check your .env file).")
        if not settings.apify_actor_id:
            raise ValueError("APIFY_ACTOR_ID is not set (check your .env file).")

        self._settings = settings
        self._client = client or ApifyClient(settings.apify_api_token)

    def fetch_samples(
        self,
        params: dict[str, Any],
        *,
        context: Optional[str] = None,
        persist_telemetry: bool = True,
    ) -> ScrapeResult:
        run = self._client.actor(self._settings.apify_actor_id).call(run_input=params)
        dataset_id = run["defaultDatasetId"]
        items = self._client.dataset(dataset_id).list_items().items
        record = apify_run_record_from_response(
            run,
            actor_id=self._settings.apify_actor_id,
            scraper="linkedin_posts",
            item_count=len(items),
            context=context,
        )
        if persist_telemetry:
            save_apify_run(record, self._settings)
        return ScrapeResult(items=items, run_record=record)
