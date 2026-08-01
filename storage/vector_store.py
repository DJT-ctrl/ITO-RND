"""Connects to Postgres+pgvector and persists posts+embeddings (T1.4/T1.5).

Intentionally separate from storage/processed_store.py (CSV/JSONL) and
storage/sample_store.py (raw JSON) — this is the first storage backend that
talks to a database instead of the filesystem, so it gets its own module
per the separation those two files already anticipate (see the comment at
the top of processed_store.py).

Core functions:
  get_connection()  — open a psycopg connection (adapter registered later)
  create_schema()   — apply storage/schema.sql (IF NOT EXISTS)
  insert_posts()    — batched upsert of joined post records + embeddings
  get_user_voice_profile() — personalization aggregate (no extra LLM)

Nearest-neighbour retrieval (T2.2 + T10.8 soft topic prefer) lives in
``storage.similarity`` and is re-exported here for stable import paths::

    from storage.vector_store import find_similar
"""

from collections import Counter
from pathlib import Path
from typing import Any, Optional

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from config.settings import Settings
from storage.similarity import find_similar  # noqa: F401  — public re-export

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
    "follower_count",
    "author_location_text",
    "author_timezone",
    "audience_adjusted_percentile",
    "audience_adjusted_zscore",
    "hook_type",
    "tone",
    "topic",
    "niche",
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
    # Fail fast on half-open tunnels instead of hanging Streamlit page loads.
    return psycopg.connect(settings.database_url, connect_timeout=5)


def create_schema(conn: psycopg.Connection) -> None:
    """Apply storage/schema.sql (idempotent - every statement is IF NOT EXISTS),
    then modular schemas under storage/schema_modules/, then register the
    pgvector type adapter now that `vector` is guaranteed to exist.
    """
    from storage.schema_modules import apply_module_schemas

    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    apply_module_schemas(conn)
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


# Feature columns for Tier 1 corpus benchmarks — no embeddings.
_ANALYSIS_COLUMNS = [
    "word_count",
    "char_count",
    "hashtag_count",
    "emoji_count",
    "hour_of_day",
    "has_media",
    "is_job_post",
    "has_explicit_cta",
    "hook_type",
    "tone",
    "topic",
    "day_of_week",
    "engagement_percentile",
    "engagement_zscore",
    "audience_adjusted_percentile",
    "audience_adjusted_zscore",
]


def count_posts(conn: psycopg.Connection) -> int:
    """Return the number of rows in the posts table."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM posts")
        row = cur.fetchone()
    return int(row[0]) if row else 0


def fetch_posts_for_analysis(
    conn: psycopg.Connection,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return feature columns for corpus benchmark analysis (no embeddings)."""
    select_clause = ", ".join(_ANALYSIS_COLUMNS)
    sql = (
        f"SELECT {select_clause} FROM posts "
        f"WHERE engagement_anomaly_flag = FALSE "
        f"ORDER BY engagement_percentile DESC "
        f"LIMIT %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (limit,))
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

    Looks at that user's `top_n` posts by follower-adjusted rank (falling
    back to raw `engagement_percentile` for posts that never went through
    the optional profile-enrichment path) and summarizes their dominant
    hook_type/tone/writing_style, average word_count/hashtag_count, and how
    often they use an explicit CTA. Purely an aggregation over columns
    already in the `posts` table (no extra Gemini call) — cheap enough to
    run on every personalized request.

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
        f"ORDER BY COALESCE(audience_adjusted_percentile, engagement_percentile) DESC "
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
