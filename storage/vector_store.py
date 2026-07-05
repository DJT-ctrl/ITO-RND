"""Connects to Postgres+pgvector and persists posts+embeddings (T1.4/T1.5).

Intentionally separate from storage/processed_store.py (CSV/JSONL) and
storage/sample_store.py (raw JSON) — this is the first storage backend that
talks to a database instead of the filesystem, so it gets its own module
per the separation those two files already anticipate (see the comment at
the top of processed_store.py).

Four small functions:
  get_connection()  — open a psycopg connection with the pgvector adapter
                       registered so numpy arrays can be passed directly as
                       `vector` column values.
  create_schema()   — apply storage/schema.sql (CREATE EXTENSION/TABLE/INDEX,
                       all IF NOT EXISTS so it's safe to call every run).
  insert_posts()     — batched upsert of joined post records + embeddings.
  find_similar()     — T2.2: cosine-distance nearest-neighbour retrieval
                       against the halfvec(3072) HNSW index.
"""

from pathlib import Path
from typing import Any

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
    "content",
    "embedding",
]


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
        tuple(record.get(col) for col in _COLUMNS if col != "embedding") + (vector,)
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


def find_similar(conn: psycopg.Connection, query_vector: np.ndarray, limit: int = 10) -> list[dict[str, Any]]:
    """Return the `limit` posts whose embedding is closest (cosine distance)
    to query_vector, ordered nearest-first.

    Uses the halfvec(3072) HNSW index defined in storage/schema.sql — both
    sides of the `<=>` comparison are cast to halfvec(3072) so the query
    actually hits that index instead of doing a full scan (see
    T1.4_DATABASE_PLAN.md).

    Returns a list of dicts with post_id, content, engagement fields, and
    the computed cosine_distance for each match.
    """
    select_clause = ", ".join(_SIMILAR_COLUMNS)
    sql = (
        f"SELECT {select_clause}, "
        f"embedding::halfvec(3072) <=> %s::halfvec(3072) AS cosine_distance "
        f"FROM posts "
        f"ORDER BY embedding::halfvec(3072) <=> %s::halfvec(3072) "
        f"LIMIT %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (query_vector, query_vector, limit))
        columns = [col.name for col in cur.description]
        rows = cur.fetchall()
    return [dict(zip(columns, row)) for row in rows]
