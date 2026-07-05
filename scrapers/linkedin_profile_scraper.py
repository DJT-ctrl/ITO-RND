"""LinkedIn profile scraper, backed by the curious_coder/linkedin-profile-scraper
Apify actor.

Why this exists: the post-search scraper (linkedin_scraper.py) has no way to
tell whether a post did well because it's genuinely good content or because
its author has a huge following. This scraper fetches author-level data
(follower count, industry, current company, etc.) so engagement can later be
normalized by audience size instead of producing misleading "patterns".

Unlike the post scraper, this actor needs an authenticated LinkedIn session
(cookies) to load profile pages. Cookies are read from Settings only - never
hardcoded, logged, or echoed back in error messages - since they're
effectively a login credential for the LinkedIn account that exported them.
"""

from typing import Any, Optional

from apify_client import ApifyClient

from config.settings import Settings
from scrapers.base_scraper import BaseScraper


class LinkedInProfileScraper(BaseScraper):
    platform_name = "linkedin_profiles"

    # Apify's own guidance: scraping more than this per day from one LinkedIn
    # account risks it being logged out / flagged. Enforced here so a bad
    # input list can't silently take the account past that limit.
    MAX_PROFILES_PER_RUN = 500

    def __init__(self, settings: Settings, client: Optional[ApifyClient] = None):
        if not settings.apify_api_token:
            raise ValueError("APIFY_API_TOKEN is not set (check your .env file).")
        if not settings.apify_profile_actor_id:
            raise ValueError("APIFY_PROFILE_ACTOR_ID is not set (check your .env file).")

        self._settings = settings
        self._client = client or ApifyClient(settings.apify_api_token)

    def fetch_samples(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Fetch profile data for the LinkedIn profile URLs given in params.

        Expected params:
            profileUrls (required): list[str] of LinkedIn profile URLs.
            Any other keys (e.g. proxy config) are passed straight through
            to the actor untouched.
        """
        profile_urls = params.get("profileUrls", [])
        if not profile_urls:
            raise ValueError("params['profileUrls'] must contain at least one profile URL.")
        if len(profile_urls) > self.MAX_PROFILES_PER_RUN:
            raise ValueError(
                f"Requested {len(profile_urls)} profiles, which exceeds the "
                f"{self.MAX_PROFILES_PER_RUN}/day safety limit for a single "
                "LinkedIn account. Split the run across multiple days."
            )

        extra_params = {k: v for k, v in params.items() if k != "profileUrls"}
        run_input: dict[str, Any] = {"urls": profile_urls, **extra_params}

        # Only inject cookies if they were configured.  Some actor variants
        # (e.g. the no-cookie version) don't accept this field at all.
        if self._settings.linkedin_cookies:
            run_input["cookie"] = self._settings.linkedin_cookies

        run = self._client.actor(self._settings.apify_profile_actor_id).call(run_input=run_input)
        dataset_id = run["defaultDatasetId"]
        return self._client.dataset(dataset_id).list_items().items
