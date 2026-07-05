"""Unit tests for storage/vector_store.py (T1.4/T1.5).

All Postgres interaction is mocked - no real database is required to run
these tests, consistent with how tests/test_embedder.py mocks the Gemini
client instead of making real API calls.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from config.settings import Settings
from storage.vector_store import create_schema, find_similar, get_connection, insert_posts


def make_settings(**overrides) -> Settings:
    defaults = dict(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="",
        raw_data_dir="data/raw",
        default_search_limit=10,
        database_url="postgresql://ito:test@localhost:5432/ito_posts",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def make_record(post_id: str) -> dict:
    """A minimal-but-complete record covering every storage/schema.sql column."""
    return {
        "post_id": post_id,
        "author_public_id": "author-1",
        "linkedin_url": "https://linkedin.com/in/author-1",
        "likes": 10,
        "comments": 2,
        "shares": 1,
        "total_engagement": 13,
        "comment_ratio": 0.15,
        "share_ratio": 0.07,
        "word_count": 50,
        "char_count": 300,
        "hashtag_count": 2,
        "emoji_count": 0,
        "has_media": False,
        "is_job_post": False,
        "hour_of_day": 9,
        "day_of_week": "Monday",
        "engagement_percentile": 75.0,
        "engagement_zscore": 0.8,
        "engagement_rate": None,
        "hook_type": None,
        "tone": None,
        "topic": None,
        "has_explicit_cta": None,
        "writing_style": None,
        "content": "Some post content that is long enough to be valid.",
    }


def make_mock_conn() -> MagicMock:
    """A MagicMock shaped like a psycopg.Connection with a usable cursor()."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn


# ── get_connection ───────────────────────────────────────────────────────

def test_get_connection_raises_without_database_url():
    with pytest.raises(ValueError):
        get_connection(make_settings(database_url=""))


@patch("storage.vector_store.psycopg.connect")
def test_get_connection_connects_without_registering_vector_yet(mock_connect):
    """register_vector() must NOT be called here - the `vector` extension may
    not exist yet on a brand-new database. create_schema() registers it once
    CREATE EXTENSION is guaranteed to have run.
    """
    mock_conn = MagicMock()
    mock_connect.return_value = mock_conn
    settings = make_settings()

    result = get_connection(settings)

    mock_connect.assert_called_once_with(settings.database_url)
    assert result is mock_conn


# ── create_schema ────────────────────────────────────────────────────────

@patch("storage.vector_store.register_vector")
def test_create_schema_executes_schema_sql_and_commits(mock_register):
    conn = make_mock_conn()
    cursor = conn.cursor.return_value.__enter__.return_value

    create_schema(conn)

    assert cursor.execute.call_count == 1
    executed_sql = cursor.execute.call_args[0][0]
    assert "CREATE EXTENSION IF NOT EXISTS vector" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS posts" in executed_sql
    assert "hnsw" in executed_sql
    conn.commit.assert_called_once()
    mock_register.assert_called_once_with(conn)


# ── insert_posts ─────────────────────────────────────────────────────────

def test_insert_posts_raises_on_length_mismatch():
    conn = make_mock_conn()
    records = [make_record("1"), make_record("2")]
    vectors = np.zeros((1, 3072), dtype=np.float32)

    with pytest.raises(ValueError):
        insert_posts(conn, records, vectors)


def test_insert_posts_returns_row_count():
    conn = make_mock_conn()
    records = [make_record(str(i)) for i in range(5)]
    vectors = np.zeros((5, 3072), dtype=np.float32)

    count = insert_posts(conn, records, vectors)

    assert count == 5
    conn.commit.assert_called_once()


def test_insert_posts_batches_correctly():
    """250 rows with batch_size=100 should trigger 3 executemany calls."""
    conn = make_mock_conn()
    cursor = conn.cursor.return_value.__enter__.return_value
    records = [make_record(str(i)) for i in range(250)]
    vectors = np.zeros((250, 3072), dtype=np.float32)

    insert_posts(conn, records, vectors, batch_size=100)

    assert cursor.executemany.call_count == 3
    batch_sizes = [len(call.args[1]) for call in cursor.executemany.call_args_list]
    assert batch_sizes == [100, 100, 50]


def test_insert_posts_uses_upsert_on_post_id():
    conn = make_mock_conn()
    cursor = conn.cursor.return_value.__enter__.return_value
    records = [make_record("1")]
    vectors = np.zeros((1, 3072), dtype=np.float32)

    insert_posts(conn, records, vectors)

    insert_sql = cursor.executemany.call_args[0][0]
    assert "ON CONFLICT (post_id) DO UPDATE" in insert_sql


# ── find_similar ─────────────────────────────────────────────────────────

def make_row_columns(cursor, columns: list[str]):
    cursor.description = [MagicMock(name=col) for col in columns]
    for mock_col, name in zip(cursor.description, columns):
        mock_col.name = name


def test_find_similar_query_shape():
    conn = make_mock_conn()
    cursor = conn.cursor.return_value.__enter__.return_value
    columns = [
        "post_id",
        "content",
        "likes",
        "comments",
        "shares",
        "total_engagement",
        "engagement_percentile",
        "engagement_zscore",
        "cosine_distance",
    ]
    make_row_columns(cursor, columns)
    cursor.fetchall.return_value = []

    query_vector = np.zeros(3072, dtype=np.float32)
    find_similar(conn, query_vector, limit=10)

    executed_sql = cursor.execute.call_args[0][0]
    assert "halfvec(3072)" in executed_sql
    assert "<=>" in executed_sql
    assert "LIMIT" in executed_sql

    executed_params = cursor.execute.call_args[0][1]
    assert executed_params[2] == 10


def test_find_similar_returns_dicts_matching_rows():
    conn = make_mock_conn()
    cursor = conn.cursor.return_value.__enter__.return_value
    columns = [
        "post_id",
        "content",
        "likes",
        "comments",
        "shares",
        "total_engagement",
        "engagement_percentile",
        "engagement_zscore",
        "cosine_distance",
    ]
    make_row_columns(cursor, columns)
    cursor.fetchall.return_value = [
        ("1", "hello world", 10, 2, 1, 13, 75.0, 0.8, 0.05),
    ]

    query_vector = np.zeros(3072, dtype=np.float32)
    results = find_similar(conn, query_vector, limit=1)

    assert results == [
        {
            "post_id": "1",
            "content": "hello world",
            "likes": 10,
            "comments": 2,
            "shares": 1,
            "total_engagement": 13,
            "engagement_percentile": 75.0,
            "engagement_zscore": 0.8,
            "cosine_distance": 0.05,
        }
    ]
