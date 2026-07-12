"""Unit tests for LinkedIn profile scraper."""

from unittest.mock import MagicMock

import pytest

from config.settings import Settings
from scrapers.linkedin_profile_scraper import LinkedInProfileScraper
from scrapers.result import ScrapeResult


def make_settings(**overrides) -> Settings:
    defaults = dict(
        apify_api_token="test-token",
        apify_actor_id="test-actor",
        apify_profile_actor_id="test-profile-actor",
        linkedin_cookies=[],
        gemini_api_key="",
        raw_data_dir="data/raw",
        default_search_limit=10,
        telemetry_data_dir="data/telemetry",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _fake_run(**extra):
    base = {
        "id": "run-profile-1",
        "status": "SUCCEEDED",
        "defaultDatasetId": "dataset-456",
        "usageTotalUsd": 1.25,
        "stats": {"computeUnits": 3.2},
    }
    base.update(extra)
    return base


def test_fetch_samples_returns_raw_items_untouched(tmp_path, monkeypatch):
    fake_items = [{"publicIdentifier": "someone", "followerCount": 1000}]

    mock_client = MagicMock()
    mock_client.actor.return_value.call.return_value = _fake_run()
    mock_client.dataset.return_value.list_items.return_value.items = fake_items

    monkeypatch.setattr("scrapers.linkedin_profile_scraper.save_apify_run", lambda record, s: None)

    scraper = LinkedInProfileScraper(make_settings(telemetry_data_dir=str(tmp_path / "telemetry")), client=mock_client)
    result = scraper.fetch_samples({"profileUrls": ["https://www.linkedin.com/in/raulnquinones"]})

    assert isinstance(result, ScrapeResult)
    assert result.items == fake_items
    assert result.run_record is not None
    assert result.run_record.cost_usd == pytest.approx(1.25)
    assert result.run_record.scraper == "linkedin_profiles"


def test_missing_api_token_raises():
    with pytest.raises(ValueError):
        LinkedInProfileScraper(make_settings(apify_api_token=""))


def test_missing_profile_actor_raises():
    with pytest.raises(ValueError):
        LinkedInProfileScraper(make_settings(apify_profile_actor_id=""))


def test_empty_profile_urls_raises():
    scraper = LinkedInProfileScraper(make_settings(), client=MagicMock())
    with pytest.raises(ValueError):
        scraper.fetch_samples({"profileUrls": []})


def test_too_many_profile_urls_raises():
    scraper = LinkedInProfileScraper(make_settings(), client=MagicMock())
    urls = [f"https://www.linkedin.com/in/user{i}" for i in range(501)]
    with pytest.raises(ValueError):
        scraper.fetch_samples({"profileUrls": urls})
