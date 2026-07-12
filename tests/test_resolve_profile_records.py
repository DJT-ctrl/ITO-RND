"""Integration tests for cache-first profile resolution (_resolve_profile_records)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from processors.run_sample_collection import _resolve_profile_records
from scrapers.result import ScrapeResult
from telemetry.apify_schemas import ApifyRunRecord


def _settings(*, database_url: str = "postgresql://test") -> Settings:
    return Settings(
        apify_api_token="token",
        apify_actor_id="actor",
        apify_profile_actor_id="profile-actor",
        linkedin_cookies=[],
        gemini_api_key="",
        raw_data_dir="data/raw",
        default_search_limit=10,
        database_url=database_url,
        profile_cache_staleness_days=30,
    )


def _personal_post(author_id: str) -> dict:
    return {
        "id": f"post-{author_id}",
        "author": {
            "type": "profile",
            "publicIdentifier": author_id,
            "linkedinUrl": f"https://www.linkedin.com/in/{author_id}",
        },
    }


def _fresh_cache_row(author_id: str, *, follower_count: int = 1000) -> dict:
    return {
        "author_public_id": author_id,
        "follower_count": follower_count,
        "connections_count": None,
        "headline": None,
        "location_text": None,
        "is_business": False,
        "linkedin_url": f"https://www.linkedin.com/in/{author_id}",
        "scraped_at": datetime.now(timezone.utc) - timedelta(days=1),
    }


def _stale_cache_row(author_id: str) -> dict:
    row = _fresh_cache_row(author_id)
    row["scraped_at"] = datetime.now(timezone.utc) - timedelta(days=31)
    return row


@patch("processors.run_sample_collection.LinkedInProfileScraper")
@patch("processors.run_sample_collection.get_connection")
@patch("processors.run_sample_collection.create_schema")
@patch("processors.run_sample_collection.get_profile")
def test_all_fresh_cache_hits_skip_apify(
    mock_get_profile, mock_create_schema, mock_get_connection, mock_scraper_cls
):
    posts = [_personal_post("alice"), _personal_post("bob")]
    mock_get_profile.side_effect = lambda _conn, author_id: _fresh_cache_row(author_id)
    mock_get_connection.return_value = MagicMock()

    records, urls_to_scrape, fresh_records = _resolve_profile_records(
        posts, _settings(), use_profile_cache=True, profile_url_limit=None
    )

    mock_scraper_cls.assert_not_called()
    assert urls_to_scrape == []
    assert fresh_records == []
    assert len(records) == 2
    assert {r["publicIdentifier"] for r in records} == {"alice", "bob"}
    assert all(r["followerCount"] == 1000 for r in records)


@patch("processors.run_sample_collection.upsert_profile")
@patch("processors.run_sample_collection.LinkedInProfileScraper")
@patch("processors.run_sample_collection.get_connection")
@patch("processors.run_sample_collection.create_schema")
@patch("processors.run_sample_collection.get_profile")
def test_mixed_stale_and_fresh_scrapes_only_stale(
    mock_get_profile,
    mock_create_schema,
    mock_get_connection,
    mock_scraper_cls,
    mock_upsert,
):
    posts = [_personal_post("alice"), _personal_post("bob")]
    mock_get_profile.side_effect = lambda _conn, author_id: (
        _fresh_cache_row(author_id) if author_id == "alice" else _stale_cache_row(author_id)
    )
    mock_get_connection.return_value = MagicMock()

    scraper = MagicMock()
    scraper.fetch_samples.return_value = ScrapeResult(
        items=[{"publicIdentifier": "bob", "followerCount": 2000, "linkedinUrl": "https://www.linkedin.com/in/bob"}],
        run_record=ApifyRunRecord(
            run_id="r1",
            actor_id="profile-actor",
            scraper="linkedin_profiles",
            status="SUCCEEDED",
            cost_usd=0.1,
            item_count=1,
            recorded_at=datetime.now(timezone.utc),
        ),
    )
    mock_scraper_cls.return_value = scraper

    records, urls_to_scrape, fresh_records = _resolve_profile_records(
        posts, _settings(), use_profile_cache=True, profile_url_limit=None
    )

    scraper.fetch_samples.assert_called_once()
    assert urls_to_scrape == ["https://www.linkedin.com/in/bob"]
    assert len(fresh_records) == 1
    assert fresh_records[0]["publicIdentifier"] == "bob"
    assert {r["publicIdentifier"] for r in records} == {"alice", "bob"}
    assert next(r for r in records if r["publicIdentifier"] == "alice")["followerCount"] == 1000
    assert next(r for r in records if r["publicIdentifier"] == "bob")["followerCount"] == 2000
    mock_upsert.assert_called_once()


@patch("processors.run_sample_collection.LinkedInProfileScraper")
def test_no_database_url_scrapes_all_personal_urls(mock_scraper_cls):
    posts = [_personal_post("alice"), _personal_post("bob")]
    scraper = MagicMock()
    scraper.fetch_samples.return_value = ScrapeResult(
        items=[
            {"publicIdentifier": "alice", "followerCount": 100},
            {"publicIdentifier": "bob", "followerCount": 200},
        ]
    )
    mock_scraper_cls.return_value = scraper

    records, urls_to_scrape, fresh_records = _resolve_profile_records(
        posts, _settings(database_url=""), use_profile_cache=True, profile_url_limit=None
    )

    scraper.fetch_samples.assert_called_once()
    assert set(urls_to_scrape) == {
        "https://www.linkedin.com/in/alice",
        "https://www.linkedin.com/in/bob",
    }
    assert len(fresh_records) == 2
    assert len(records) == 2


@patch("processors.run_sample_collection.upsert_profile")
@patch("processors.run_sample_collection.LinkedInProfileScraper")
@patch("processors.run_sample_collection.get_connection")
@patch("processors.run_sample_collection.create_schema")
@patch("processors.run_sample_collection.get_profile")
def test_use_profile_cache_false_scrapes_despite_fresh_db(
    mock_get_profile,
    mock_create_schema,
    mock_get_connection,
    mock_scraper_cls,
    mock_upsert,
):
    posts = [_personal_post("alice")]
    mock_get_profile.return_value = _fresh_cache_row("alice")
    mock_get_connection.return_value = MagicMock()

    scraper = MagicMock()
    scraper.fetch_samples.return_value = ScrapeResult(
        items=[{"publicIdentifier": "alice", "followerCount": 999}]
    )
    mock_scraper_cls.return_value = scraper

    records, urls_to_scrape, fresh_records = _resolve_profile_records(
        posts, _settings(), use_profile_cache=False, profile_url_limit=None
    )

    mock_get_profile.assert_not_called()
    scraper.fetch_samples.assert_called_once()
    call_kwargs = scraper.fetch_samples.call_args
    assert call_kwargs.args[0] == {"profileUrls": ["https://www.linkedin.com/in/alice"]}
    assert urls_to_scrape == ["https://www.linkedin.com/in/alice"]
    assert records[0]["followerCount"] == 999
    mock_upsert.assert_not_called()
