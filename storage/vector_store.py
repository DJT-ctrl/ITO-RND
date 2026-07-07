"""Connects to Postgres+pgvector and persists posts+embeddings (T1.4/T1.5).

Intentionally separate from storage/processed_store.py (CSV/JSONL) and
storage/sample_store.py (raw JSON) — this is the first storage backend that
talks to a database instead of the filesystem, so it gets its own module
per the separation those two files already anticipate (see the comment at
the top of processed_store.py).

Six small functions:
  get_connection()  — open a psycopg connection with the pgvector adapter
                       registered so numpy arrays can be passed directly as
                       `vector` column values.
  create_schema()   — apply storage/schema.sql (CREATE EXTENSION/TABLE/INDEX,
                       all IF NOT EXISTS so it's safe to call every run).
  insert_posts()     — batched upsert of joined post records + embeddings.
  find_similar()     — T2.2: cosine-distance nearest-neighbour retrieval
                       against the halfvec(3072) HNSW index. Optionally
                       tenant-scoped by user_id (personalization), with an
                       automatic cold-start fallback to the global corpus.
  get_user_voice_profile() — personalization: aggregate a subscriber's own
                       top-performing posts into a lightweight "voice
                       profile" (dominant hook/tone/style, avg length, CTA
                       usage), purely from columns already in the table —
                       no extra LLM call. Returns None below a minimum post
                       count (cold start).
"""

from collections import Counter
from pathlib import Path
from typing import Any, Optional

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from config.settings import Settings

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
_BATCH_SIZE = 100

# Column order for INSERT, matching storage/schema.sql (excluding the
# server-generated `inserted_at` default).
_COLUMNS = [
    "post_id",
    "author_public_id",
    "linkedin_url",
    "user_id",
    "likes",
    "comments",
    "shares",
    "total_engagement",
    "comment_ratio",
    "share_ratio",
    "word_count",
    "char_count",
    "hashtag_count",
    "emoji_count",
    "has_media",
    "is_job_post",
    "hour_of_day",
    "day_of_week",
    "engagement_percentile",
    "engagement_zscore",
    "engagement_rate",
    "hook_type",
    "tone",
    "topic",
    "has_explicit_cta",
    "writing_style",
    "engagement_anomaly_flag",
    "anomaly_reasons",
    "content",
    "embedding",
]

# Fallback values for columns that are NOT NULL in storage/schema.sql but
# didn't exist in processed datasets generated before they were added —
# record.get(col, default) only kicks in when the key is entirely MISSING
# (not merely None), so this keeps older data/processed/*.jsonl files
# ingestable without a NOT NULL violation.
_COLUMN_DEFAULTS: dict[str, Any] = {
    "engagement_anomaly_flag": False,
    "anomaly_reasons": [],
    "user_id": None,
}


def get_connection(settings: Settings) -> psycopg.Connection:
    """Open a plain psycopg connection (no pgvector adapter registered yet).

    The pgvector type adapter can only be registered *after* `CREATE
    EXTENSION vector` has actually run against this database — registering
    it here, before create_schema() has a chance to run, fails with
    "vector type not found in the database" on a brand-new database. Call
    create_schema() (which registers the adapter itself, once the extension
    is guaranteed to exist) before passing this connection to insert_posts().

    Raises:
        ValueError: if settings.database_url is not set.
    """
    if not settings.database_url:
        raise ValueError("DATABASE_URL is not set (check your .env file).")
    return psycopg.connect(settings.database_url)


def create_schema(conn: psycopg.Connection) -> None:
    """Apply storage/schema.sql (idempotent - every statement is IF NOT EXISTS),
    then register the pgvector type adapter now that `vector` is guaranteed
    to exist in this database.
    """
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    register_vector(conn)


def insert_posts(
    conn: psycopg.Connection,
    records: list[dict[str, Any]],
    vectors: np.ndarray,
    batch_size: int = _BATCH_SIZE,
) -> int:
    """Upsert joined post records + their embeddings, chunked by batch_size.

    ``records[i]`` must correspond to ``vectors[i]`` — the same pairing
    contract processors/run_embeddings.py uses (both derived from the same
    word_count >= 10 / non-blank-content filter).

    Uses ``ON CONFLICT (post_id) DO UPDATE`` so re-running ingestion for the
    same dataset is safe (updates rather than duplicating rows).

    Returns:
        Number of rows upserted.
    """
    if len(records) != len(vectors):
        raise ValueError(f"records ({len(records)}) and vectors ({len(vectors)}) length mismatch")

    placeholders = ", ".join(["%s"] * len(_COLUMNS))
    update_clause = ", ".join(f"{col} = EXCLUDED.{col}" for col in _COLUMNS if col != "post_id")
    insert_sql = (
        f"INSERT INTO posts ({', '.join(_COLUMNS)}) VALUES ({placeholders}) "
        f"ON CONFLICT (post_id) DO UPDATE SET {update_clause}"
    )

    rows = [
        tuple(
            record.get(col, _COLUMN_DEFAULTS.get(col)) for col in _COLUMNS if col != "embedding"
        )
        + (vector,)
        for record, vector in zip(records, vectors)
    ]

    with conn.cursor() as cur:
        for start in range(0, len(rows), batch_size):
            cur.executemany(insert_sql, rows[start : start + batch_size])
    conn.commit()
    return len(rows)


# Columns returned by find_similar(), in SELECT order (excluding the
# computed cosine_distance, added separately below).
_SIMILAR_COLUMNS = [
    "post_id",
    "content",
    "likes",
    "comments",
    "shares",
    "total_engagement",
    "engagement_percentile",
    "engagement_zscore",
]


def find_similar(
    conn: psycopg.Connection,
    query_vector: np.ndarray,
    limit: int = 10,
    user_id: Optional[str] = None,
    fallback_to_global: bool = True,
    min_user_results: int = 3,
) -> list[dict[str, Any]]:
    """Return the `limit` posts whose embedding is closest (cosine distance)
    to query_vector, ordered nearest-first.

    Uses the halfvec(3072) HNSW index defined in storage/schema.sql — both
    sides of the `<=>` comparison are cast to halfvec(3072) so the query
    actually hits that index instead of doing a full scan (see
    T1.4_DATABASE_PLAN.md).

    Tenant scoping (personalization): if `user_id` is given, the search is
    first restricted to that subscriber's own posts (`WHERE user_id = %s`).
    If fewer than `min_user_results` rows come back (cold start — a new or
    low-volume subscriber) and `fallback_to_global` is True (default), the
    query is re-run unfiltered against the whole corpus instead, so callers
    always get useful neighbors rather than a near-empty result.

    Returns a list of dicts with post_id, content, engagement fields, and
    the computed cosine_distance for each match.
    """
    rows = _find_similar_query(conn, query_vector, limit, user_id)
    if user_id is not None and len(rows) < min_user_results and fallback_to_global:
        rows = _find_similar_query(conn, query_vector, limit, user_id=None)
    return rows


def _find_similar_query(
    conn: psycopg.Connection,
    query_vector: np.ndarray,
    limit: int,
    user_id: Optional[str],
) -> list[dict[str, Any]]:
    """Run the actual cosine-distance query, optionally filtered by user_id."""
    select_clause = ", ".join(_SIMILAR_COLUMNS)
    where_clause = "WHERE user_id = %s " if user_id is not None else ""
    sql = (
        f"SELECT {select_clause}, "
        f"embedding::halfvec(3072) <=> %s::halfvec(3072) AS cosine_distance "
        f"FROM posts "
        f"{where_clause}"
        f"ORDER BY embedding::halfvec(3072) <=> %s::halfvec(3072) "
        f"LIMIT %s"
    )
    params = (
        (query_vector, user_id, query_vector, limit)
        if user_id is not None
        else (query_vector, query_vector, limit)
    )
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [col.name for col in cur.description]
        rows = cur.fetchall()
    return [dict(zip(columns, row)) for row in rows]


# Columns aggregated by get_user_voice_profile() — all already populated by
# Stage 2 Gemini tagging (processors/run_pipeline.py --with-gemini) and
# Stage 1 content-shape features, so the voice profile costs zero extra
# LLM calls, just a SQL query + Python aggregation.
_VOICE_PROFILE_COLUMNS = [
    "hook_type",
    "tone",
    "writing_style",
    "has_explicit_cta",
    "word_count",
    "hashtag_count",
]


def get_user_voice_profile(
    conn: psycopg.Connection,
    user_id: str,
    top_n: int = 10,
    min_posts: int = 3,
) -> Optional[dict[str, Any]]:
    """Derive a lightweight "voice profile" from a subscriber's own
    top-performing posts (personalization — dynamic style-profile
    prompting).

    Looks at that user's `top_n` posts by `engagement_percentile` and
    summarizes their dominant hook_type/tone/writing_style, average
    word_count/hashtag_count, and how often they use an explicit CTA.
    Purely an aggregation over columns already in the `posts` table (no
    extra Gemini call) — cheap enough to run on every personalized request.

    Returns:
        None if fewer than `min_posts` posts exist for this user (cold
        start — not enough data for a meaningful profile; callers should
        fall back to the generic, non-personalized system prompt). Otherwise
        a dict with dominant_hook_type, dominant_tone, dominant_writing_style,
        avg_word_count, avg_hashtag_count, cta_usage_ratio, and
        sample_size (how many posts the profile was computed from).
    """
    select_clause = ", ".join(_VOICE_PROFILE_COLUMNS)
    sql = (
        f"SELECT {select_clause} FROM posts "
        f"WHERE user_id = %s "
        f"ORDER BY engagement_percentile DESC "
        f"LIMIT %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (user_id, top_n))
        columns = [col.name for col in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]

    if len(rows) < min_posts:
        return None

    def _mode(values: list[Optional[str]]) -> Optional[str]:
        present = [value for value in values if value]
        if not present:
            return None
        return Counter(present).most_common(1)[0][0]

    word_counts = [row["word_count"] for row in rows if row["word_count"] is not None]
    hashtag_counts = [row["hashtag_count"] for row in rows if row["hashtag_count"] is not None]
    cta_flags = [row["has_explicit_cta"] for row in rows if row["has_explicit_cta"] is not None]

    return {
        "dominant_hook_type": _mode([row["hook_type"] for row in rows]),
        "dominant_tone": _mode([row["tone"] for row in rows]),
        "dominant_writing_style": _mode([row["writing_style"] for row in rows]),
        "avg_word_count": round(sum(word_counts) / len(word_counts), 1) if word_counts else None,
        "avg_hashtag_count": round(sum(hashtag_counts) / len(hashtag_counts), 1) if hashtag_counts else None,
        "cta_usage_ratio": round(sum(cta_flags) / len(cta_flags), 2) if cta_flags else None,
        "sample_size": len(rows),
    }
