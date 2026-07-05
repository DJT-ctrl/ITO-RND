from unittest.mock import MagicMock

import pytest

from config.settings import Settings
from scrapers.linkedin_profile_scraper import LinkedInProfileScraper


def make_settings(**overrides) -> Settings:
    defaults = dict(
        apify_api_token="test-token",
        apify_actor_id="test-actor",
        apify_profile_actor_id="test-profile-actor",
        linkedin_cookies=[{"name": "li_at", "value": "fake"}],
        gemini_api_key="",
        raw_data_dir="data/raw",
        default_search_limit=10,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_fetch_samples_returns_raw_items_untouched():
    fake_items = [{"firstName": "Raul", "lastName": "Quinones"}]

    mock_client = MagicMock()
    mock_client.actor.return_value.call.return_value = {"defaultDatasetId": "dataset-123"}
    mock_client.dataset.return_value.list_items.return_value.items = fake_items

    scraper = LinkedInProfileScraper(make_settings(), client=mock_client)
    result = scraper.fetch_samples({"profileUrls": ["https://www.linkedin.com/in/raulnquinones"]})

    assert result == fake_items
    mock_client.actor.assert_called_once_with("test-profile-actor")
    mock_client.actor.return_value.call.assert_called_once_with(
        run_input={
            "cookie": [{"name": "li_at", "value": "fake"}],
            "urls": ["https://www.linkedin.com/in/raulnquinones"],
        }
    )

def test_missing_api_token_raises():
    with pytest.raises(ValueError):
        LinkedInProfileScraper(make_settings(apify_api_token=""))


def test_missing_profile_actor_id_raises():
    with pytest.raises(ValueError):
        LinkedInProfileScraper(make_settings(apify_profile_actor_id=""))


def test_missing_cookies_raises():
    # Missing cookies no longer raise - cookies are optional (some actor variants
    # don't use them). The actor itself will error if it needs them and they're absent.
    scraper = LinkedInProfileScraper(make_settings(linkedin_cookies=[]))
    assert scraper is not None


def test_empty_profile_urls_raises():
    scraper = LinkedInProfileScraper(make_settings(), client=MagicMock())
    with pytest.raises(ValueError):
        scraper.fetch_samples({"profileUrls": []})


def test_too_many_profile_urls_raises():
    scraper = LinkedInProfileScraper(make_settings(), client=MagicMock())
    urls = [f"https://www.linkedin.com/in/user{i}" for i in range(501)]
    with pytest.raises(ValueError):
        scraper.fetch_samples({"profileUrls": urls})
