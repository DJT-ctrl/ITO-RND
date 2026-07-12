"""Unit tests for LinkedIn post-URL scraper."""

from unittest.mock import MagicMock

from config.settings import Settings
from scrapers.linkedin_post_url_scraper import LinkedInPostUrlScraper
from scrapers.result import ScrapeResult


def make_settings(**overrides) -> Settings:
    defaults = dict(
        apify_api_token="test-token",
        apify_actor_id="test-actor",
        apify_profile_actor_id="test-profile-actor",
        apify_post_url_actor_id="test-post-url-actor",
        linkedin_cookies=[],
        gemini_api_key="",
        raw_data_dir="data/raw",
        default_search_limit=10,
        telemetry_data_dir="data/telemetry",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_can_instantiate_and_fetch_samples_by_url(tmp_path, monkeypatch):
    fake_items = [{"url": "https://www.linkedin.com/posts/foo", "likes": 3}]
    settings = make_settings(telemetry_data_dir=str(tmp_path / "telemetry"))

    mock_client = MagicMock()
    mock_client.actor.return_value.call.return_value = {
        "id": "run-1",
        "status": "SUCCEEDED",
        "defaultDatasetId": "dataset-1",
    }
    mock_client.dataset.return_value.list_items.return_value.items = fake_items

    monkeypatch.setattr(
        "scrapers.linkedin_post_url_scraper.save_apify_run",
        lambda record, s: None,
    )

    scraper = LinkedInPostUrlScraper(settings, client=mock_client)
    result = scraper.fetch_samples(
        {"targetUrls": ["https://www.linkedin.com/posts/foo"]},
        persist_telemetry=False,
    )

    assert isinstance(result, ScrapeResult)
    assert result.items == fake_items
