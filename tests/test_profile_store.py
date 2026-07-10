"""Unit tests for the profiles scrape cache (storage/profile_store.py)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from storage.profile_store import (
    is_profile_stale,
    profile_record_from_enriched_post,
    profile_record_from_harvestapi,
)


def test_is_profile_stale_when_missing():
    assert is_profile_stale(None, staleness_days=30) is True


def test_is_profile_stale_when_fresh():
    profile = {"scraped_at": datetime.now(timezone.utc) - timedelta(days=1)}
    assert is_profile_stale(profile, staleness_days=30) is False


def test_is_profile_stale_when_old():
    profile = {"scraped_at": datetime.now(timezone.utc) - timedelta(days=31)}
    assert is_profile_stale(profile, staleness_days=30) is True


def test_profile_record_from_harvestapi():
    record = profile_record_from_harvestapi(
        {
            "publicIdentifier": "alice",
            "followerCount": 1200,
            "connectionsCount": 500,
            "headline": "Builder",
            "linkedinUrl": "https://www.linkedin.com/in/alice",
            "location": {"linkedinText": "London, UK"},
        }
    )
    assert record is not None
    assert record["author_public_id"] == "alice"
    assert record["follower_count"] == 1200
    assert record["location_text"] == "London, UK"


def test_profile_record_from_enriched_post_business_author():
    post = {
        "author": {
            "publicIdentifier": "acme",
            "universalName": "acme",
            "linkedinUrl": "https://www.linkedin.com/company/acme",
        },
        "follower_count": 2402,
        "is_business": True,
    }
    record = profile_record_from_enriched_post(post)
    assert record is not None
    assert record["author_public_id"] == "acme"
    assert record["follower_count"] == 2402
    assert record["is_business"] is True


def test_get_follower_count_returns_cached_value():
    from types import SimpleNamespace

    from storage.profile_store import get_follower_count

    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = (
        "alice",
        500,
        None,
        None,
        None,
        False,
        None,
        datetime.now(timezone.utc),
    )
    cursor.description = [
        SimpleNamespace(name=name)
        for name in [
            "author_public_id",
            "follower_count",
            "connections_count",
            "headline",
            "location_text",
            "is_business",
            "linkedin_url",
            "scraped_at",
        ]
    ]
    conn.cursor.return_value.__enter__.return_value = cursor

    assert get_follower_count(conn, "alice") == 500
