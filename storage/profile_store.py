"""Profiles scrape cache (T6.6) — keyed by author_public_id.

Before firing a paid profile scrape, check this table first and only
re-scrape when the record is stale (default 30 days, see Settings).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import psycopg


_PROFILE_COLUMNS = (
    "author_public_id",
    "follower_count",
    "connections_count",
    "headline",
    "location_text",
    "is_business",
    "linkedin_url",
    "scraped_at",
)


def upsert_profile(conn: psycopg.Connection, record: dict[str, Any]) -> None:
    """Insert or update one cached author profile."""
    sql = """
        INSERT INTO profiles (
            author_public_id, follower_count, connections_count, headline,
            location_text, is_business, linkedin_url, scraped_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now()))
        ON CONFLICT (author_public_id) DO UPDATE SET
            follower_count = EXCLUDED.follower_count,
            connections_count = EXCLUDED.connections_count,
            headline = EXCLUDED.headline,
            location_text = EXCLUDED.location_text,
            is_business = EXCLUDED.is_business,
            linkedin_url = EXCLUDED.linkedin_url,
            scraped_at = EXCLUDED.scraped_at
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                record["author_public_id"],
                record.get("follower_count"),
                record.get("connections_count"),
                record.get("headline"),
                record.get("location_text"),
                record.get("is_business", False),
                record.get("linkedin_url"),
                record.get("scraped_at"),
            ),
        )
    conn.commit()


def upsert_profiles(conn: psycopg.Connection, records: list[dict[str, Any]]) -> int:
    """Batch upsert cached author profiles. Returns rows written."""
    for record in records:
        upsert_profile(conn, record)
    return len(records)


def get_profile(conn: psycopg.Connection, author_public_id: str) -> Optional[dict[str, Any]]:
    """Return a cached profile row, or None if not found."""
    select_clause = ", ".join(_PROFILE_COLUMNS)
    sql = f"SELECT {select_clause} FROM profiles WHERE author_public_id = %s"
    with conn.cursor() as cur:
        cur.execute(sql, (author_public_id,))
        row = cur.fetchone()
        if row is None:
            return None
        columns = [col.name for col in cur.description]
    return dict(zip(columns, row))


def get_follower_count(conn: psycopg.Connection, author_public_id: str) -> Optional[int]:
    """Return cached follower_count for an author, or None."""
    profile = get_profile(conn, author_public_id)
    if profile is None:
        return None
    return profile.get("follower_count")


def is_profile_stale(
    profile: Optional[dict[str, Any]],
    *,
    staleness_days: int,
    now: Optional[datetime] = None,
) -> bool:
    """True when the profile is missing or older than staleness_days."""
    if profile is None:
        return True
    scraped_at = profile.get("scraped_at")
    if scraped_at is None:
        return True
    if scraped_at.tzinfo is None:
        scraped_at = scraped_at.replace(tzinfo=timezone.utc)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=staleness_days)
    return scraped_at < cutoff


def list_stale_author_ids(
    conn: psycopg.Connection,
    author_public_ids: list[str],
    *,
    staleness_days: int,
) -> list[str]:
    """Return author ids with no cache row or a stale scraped_at."""
    if not author_public_ids:
        return []
    stale: list[str] = []
    for author_id in author_public_ids:
        profile = get_profile(conn, author_id)
        if is_profile_stale(profile, staleness_days=staleness_days):
            stale.append(author_id)
    return stale


def profile_record_from_enriched_post(post: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Build a profiles-table row from an enriched raw post dict."""
    author = post.get("author") or {}
    author_public_id = author.get("publicIdentifier") or author.get("universalName") or ""
    if not author_public_id:
        return None
    follower_count = post.get("follower_count")
    if follower_count is None:
        return None
    return {
        "author_public_id": author_public_id,
        "follower_count": follower_count,
        "connections_count": post.get("connections_count"),
        "headline": post.get("headline"),
        "location_text": post.get("location_text"),
        "is_business": bool(post.get("is_business")),
        "linkedin_url": author.get("linkedinUrl"),
        "scraped_at": datetime.now(timezone.utc),
    }


def profile_record_from_harvestapi(record: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Build a profiles-table row from a harvestapi profile scrape record."""
    author_public_id = record.get("publicIdentifier") or ""
    if not author_public_id:
        return None
    follower_count = record.get("followerCount")
    if follower_count is None:
        return None
    location = record.get("location") or {}
    return {
        "author_public_id": author_public_id,
        "follower_count": follower_count,
        "connections_count": record.get("connectionsCount"),
        "headline": record.get("headline"),
        "location_text": location.get("linkedinText"),
        "is_business": False,
        "linkedin_url": record.get("linkedinUrl"),
        "scraped_at": datetime.now(timezone.utc),
    }


def sync_profiles_from_enriched_posts(
    conn: psycopg.Connection,
    posts: list[dict[str, Any]],
) -> int:
    """Upsert profiles cache rows extracted from enriched post dicts."""
    count = 0
    seen: set[str] = set()
    for post in posts:
        row = profile_record_from_enriched_post(post)
        if row is None:
            continue
        author_id = row["author_public_id"]
        if author_id in seen:
            continue
        seen.add(author_id)
        upsert_profile(conn, row)
        count += 1
    return count
