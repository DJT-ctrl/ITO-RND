"""Unit tests for LinkedIn sample scraper."""

from unittest.mock import MagicMock

import pytest

from config.settings import Settings
from scrapers.linkedin_scraper import LinkedInScraper
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
        "id": "run-abc123",
        "status": "SUCCEEDED",
        "defaultDatasetId": "dataset-123",
        "usageTotalUsd": 0.42,
        "stats": {"computeUnits": 1.5},
        "startedAt": "2026-07-12T10:00:00.000Z",
        "finishedAt": "2026-07-12T10:01:00.000Z",
    }
    base.update(extra)
    return base


def test_fetch_samples_returns_raw_items_untouched(tmp_path, monkeypatch):
    fake_items = [{"text": "hello world", "likes": 5}]
    settings = make_settings(telemetry_data_dir=str(tmp_path / "telemetry"))

    mock_client = MagicMock()
    mock_client.actor.return_value.call.return_value = _fake_run()
    mock_client.dataset.return_value.list_items.return_value.items = fake_items

    monkeypatch.setattr("scrapers.linkedin_scraper.save_apify_run", lambda record, s: None)

    scraper = LinkedInScraper(settings, client=mock_client)
    result = scraper.fetch_samples({"searchTerm": "ai marketing", "maxItems": 10})

    assert isinstance(result, ScrapeResult)
    assert result.items == fake_items
    assert result.run_record is not None
    assert result.run_record.cost_usd == pytest.approx(0.42)
    assert result.run_record.scraper == "linkedin_posts"
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
