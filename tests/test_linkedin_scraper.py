from unittest.mock import MagicMock

import pytest

from config.settings import Settings
from scrapers.linkedin_scraper import LinkedInScraper


def make_settings(**overrides) -> Settings:
    defaults = dict(
        apify_api_token="test-token",
        apify_actor_id="test-actor",
        apify_profile_actor_id="test-profile-actor",
        linkedin_cookies=[],
        gemini_api_key="",
        raw_data_dir="data/raw",
        default_search_limit=10,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_fetch_samples_returns_raw_items_untouched():
    fake_items = [{"text": "hello world", "likes": 5}]

    mock_client = MagicMock()
    mock_client.actor.return_value.call.return_value = {"defaultDatasetId": "dataset-123"}
    mock_client.dataset.return_value.list_items.return_value.items = fake_items

    scraper = LinkedInScraper(make_settings(), client=mock_client)
    result = scraper.fetch_samples({"searchTerm": "ai marketing", "maxItems": 10})

    assert result == fake_items
    mock_client.actor.assert_called_once_with("test-actor")
    mock_client.actor.return_value.call.assert_called_once_with(
        run_input={"searchTerm": "ai marketing", "maxItems": 10}
    )


def test_missing_api_token_raises():
    with pytest.raises(ValueError):
        LinkedInScraper(make_settings(apify_api_token=""))


def test_missing_actor_id_raises():
    with pytest.raises(ValueError):
        LinkedInScraper(make_settings(apify_actor_id=""))
