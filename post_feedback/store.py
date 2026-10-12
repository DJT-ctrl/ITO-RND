"""Postgres read/write for stored-post feedback."""

from __future__ import annotations

import json
from typing import Any, Optional
from uuid import UUID

import numpy as np
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from feedback.store import embedding_to_float_list
from post_feedback.prompt import labels_present, select_neighbors
from post_feedback.schemas import NEIGHBOR_LIMIT, EligiblePost, PostFeedbackRecord, ReviewStatus
from storage.similarity import find_similar

# Clean posts only. Anomaly-flagged rows stay on the post-mortem lane.
# Label JSON must carry Gemini evidence or a Hugging Face section.
# Posts that already have feedback are skipped (one row per post_id).
_FETCH_ELIGIBLE_SQL = """
SELECT
    p.post_id,
    p.content,
    p.engagement_percentile,
    p.engagement_zscore,
    p.word_count,
    p.hashtag_count,
    p.has_media,
    p.hook_type,
    p.tone,
    p.topic,
    p.has_explicit_cta,
    p.writing_style,
    p.gemini_labels,
    p.huggingface_labels,
    p.embedding
FROM posts p
WHERE p.engagement_anomaly_flag = FALSE
  AND NOT EXISTS (
      SELECT 1 FROM post_feedback f WHERE f.post_id = p.post_id
  )
  AND (
      NULLIF(p.gemini_labels->>'hook_type', '') IS NOT NULL
      OR NULLIF(p.gemini_labels->>'tone', '') IS NOT NULL
      OR NULLIF(p.gemini_labels->>'topic', '') IS NOT NULL
      OR NULLIF(p.gemini_labels->>'writing_style', '') IS NOT NULL
      OR p.gemini_labels->>'has_explicit_cta' IN ('true', 'false')
      OR p.huggingface_labels->>'labeler' = 'huggingface'
  )
ORDER BY p.inserted_at DESC
LIMIT %s
"""

_INSERT_SQL = """
INSERT INTO post_feedback (
    post_id,
    summary,
    what_worked,
    what_to_change,
    neighbor_notes,
    evidence,
    review_status,
    model,
    input_tokens,
    output_tokens
) VALUES (
    %(post_id)s,
    %(summary)s,
    %(what_worked)s,
    %(what_to_change)s,
    %(neighbor_notes)s,
    %(evidence)s,
    %(review_status)s,
    %(model)s,
    %(input_tokens)s,
    %(output_tokens)s
)
ON CONFLICT (post_id) DO NOTHING
RETURNING post_feedback_id
"""

_LIST_SQL = """
SELECT
    post_feedback_id,
    post_id,
    summary,
    what_worked,
    what_to_change,
    neighbor_notes,
    evidence,
    review_status,
    reviewed_at,
    reviewed_by,
    model,
    input_tokens,
    output_tokens,
    generated_at
FROM post_feedback
ORDER BY CASE review_status WHEN 'pending' THEN 0 ELSE 1 END, generated_at DESC
LIMIT %s
"""

_SET_REVIEW_SQL = """
UPDATE post_feedback
SET review_status = %(review_status)s,
    reviewed_at = now(),
    reviewed_by = %(reviewed_by)s
WHERE post_id = %(post_id)s
RETURNING post_feedback_id
"""

_CTA_SQL = """
SELECT post_id, has_explicit_cta
FROM posts
WHERE post_id = ANY(%s)
"""


def fetch_eligible_posts(
    conn: psycopg.Connection,
    *,
    limit: int = 50,
) -> list[tuple[EligiblePost, np.ndarray]]:
    """Return labelled clean posts that do not yet have feedback, plus embeddings."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_FETCH_ELIGIBLE_SQL, (limit,))
        rows = cur.fetchall()
    eligible: list[tuple[EligiblePost, np.ndarray]] = []
    for row in rows:
        gemini = _as_dict(row["gemini_labels"])
        huggingface = _as_dict(row["huggingface_labels"])
        if not labels_present(gemini, huggingface):
            continue
        post = EligiblePost(
            post_id=row["post_id"],
            content=row["content"] or "",
            engagement_percentile=float(row["engagement_percentile"]),
            engagement_zscore=float(row["engagement_zscore"]),
            word_count=int(row["word_count"]),
            hashtag_count=int(row["hashtag_count"] or 0),
            has_media=bool(row["has_media"]),
            hook_type=row["hook_type"],
            tone=row["tone"],
            topic=row["topic"],
            has_explicit_cta=row["has_explicit_cta"],
            writing_style=row["writing_style"],
            gemini_labels=gemini,
            huggingface_labels=huggingface,
        )
        vector = np.asarray(embedding_to_float_list(row["embedding"]), dtype=np.float32)
        eligible.append((post, vector))
    return eligible


def fetch_neighbor_rows(
    conn: psycopg.Connection,
    embedding: np.ndarray,
    post_id: str,
    *,
    limit: int = NEIGHBOR_LIMIT,
) -> list[dict[str, Any]]:
    """Nearest posts from the existing embedding, excluding the source post."""
    raw = find_similar(conn, embedding, limit=limit + 1)
    neighbors = select_neighbors(raw, post_id, limit=limit)
    if not neighbors:
        return []
    cta_by_id = _fetch_cta(conn, [str(row["post_id"]) for row in neighbors])
    for row in neighbors:
        row["has_explicit_cta"] = cta_by_id.get(str(row["post_id"]))
    return neighbors


def insert_post_feedback(
    conn: psycopg.Connection,
    record: PostFeedbackRecord,
) -> Optional[UUID]:
    """Insert one row. Returns None when this post_id already has feedback."""
    payload = {
        "post_id": record.post_id,
        "summary": record.summary,
        "what_worked": record.what_worked,
        "what_to_change": record.what_to_change,
        "neighbor_notes": Jsonb(record.neighbor_notes),
        "evidence": Jsonb(record.evidence),
        "review_status": "pending",
        "model": record.model,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
    }
    with conn.cursor() as cur:
        cur.execute(_INSERT_SQL, payload)
        row = cur.fetchone()
    conn.commit()
    if not row:
        return None
    return row[0]


def list_post_feedback(
    conn: psycopg.Connection,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_LIST_SQL, (limit,))
        rows = cur.fetchall()
    return [_list_row(row) for row in rows]


def set_review_status(
    conn: psycopg.Connection,
    post_id: str,
    review_status: ReviewStatus,
    *,
    reviewed_by: str,
) -> bool:
    """Approve or reject one write-up. Returns False when the post has no row."""
    if review_status not in ("approved", "rejected"):
        raise ValueError("review_status must be approved or rejected")
    with conn.cursor() as cur:
        cur.execute(
            _SET_REVIEW_SQL,
            {
                "post_id": post_id,
                "review_status": review_status,
                "reviewed_by": reviewed_by,
            },
        )
        row = cur.fetchone()
    conn.commit()
    return row is not None


def _fetch_cta(
    conn: psycopg.Connection,
    post_ids: list[str],
) -> dict[str, Optional[bool]]:
    if not post_ids:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_CTA_SQL, (post_ids,))
        rows = cur.fetchall()
    return {str(row["post_id"]): row["has_explicit_cta"] for row in rows}


def _list_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "post_feedback_id": str(row["post_feedback_id"]),
        "post_id": row["post_id"],
        "summary": row["summary"],
        "what_worked": list(row["what_worked"] or []),
        "what_to_change": list(row["what_to_change"] or []),
        "neighbor_notes": _as_list(row["neighbor_notes"]),
        "evidence": _as_dict(row["evidence"]),
        "review_status": row["review_status"],
        "reviewed_at": row["reviewed_at"],
        "reviewed_by": row["reviewed_by"],
        "model": row["model"],
        "input_tokens": int(row["input_tokens"] or 0),
        "output_tokens": int(row["output_tokens"] or 0),
        "generated_at": row["generated_at"],
    }


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    if isinstance(value, dict):
        return value
    return {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    if isinstance(value, list):
        return value
    return []
