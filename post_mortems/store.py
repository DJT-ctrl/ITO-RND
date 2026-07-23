"""Postgres read/write for A1 post_mortems."""

from __future__ import annotations

import json
from typing import Any, Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from post_mortems.schemas import AnomalyPostRow, PostMortemRecord

_FETCH_FLAGGED_SQL = """
SELECT
    p.post_id,
    p.content,
    p.likes,
    p.comments,
    p.shares,
    p.total_engagement,
    p.comment_ratio,
    p.share_ratio,
    p.engagement_percentile,
    p.anomaly_reasons,
    p.topic,
    p.hook_type
FROM posts p
WHERE p.engagement_anomaly_flag = TRUE
  AND NOT EXISTS (
      SELECT 1 FROM post_mortems pm WHERE pm.post_id = p.post_id
  )
ORDER BY p.inserted_at DESC
LIMIT %s
"""

_INSERT_SQL = """
INSERT INTO post_mortems (
    post_id,
    machine_reasons,
    verdict,
    summary,
    evidence,
    lesson_for_models,
    model
) VALUES (
    %(post_id)s,
    %(machine_reasons)s,
    %(verdict)s,
    %(summary)s,
    %(evidence)s,
    %(lesson_for_models)s,
    %(model)s
)
ON CONFLICT (post_id) DO NOTHING
RETURNING post_mortem_id
"""

_LIST_SQL = """
SELECT
    post_mortem_id,
    post_id,
    machine_reasons,
    verdict,
    summary,
    evidence,
    lesson_for_models,
    model,
    generated_at
FROM post_mortems
ORDER BY generated_at DESC
LIMIT %s
"""


def fetch_flagged_posts_without_mortems(
    conn: psycopg.Connection,
    *,
    limit: int = 50,
) -> list[AnomalyPostRow]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_FETCH_FLAGGED_SQL, (limit,))
        rows = cur.fetchall()
    return [
        AnomalyPostRow(
            post_id=r["post_id"],
            content=r["content"] or "",
            likes=int(r["likes"]),
            comments=int(r["comments"]),
            shares=int(r["shares"]),
            total_engagement=int(r["total_engagement"]),
            comment_ratio=r["comment_ratio"],
            share_ratio=r["share_ratio"],
            engagement_percentile=float(r["engagement_percentile"]),
            anomaly_reasons=list(r["anomaly_reasons"] or []),
            topic=r["topic"],
            hook_type=r["hook_type"],
        )
        for r in rows
    ]


def insert_post_mortem(
    conn: psycopg.Connection,
    record: PostMortemRecord,
) -> Optional[UUID]:
    payload = {
        "post_id": record.post_id,
        "machine_reasons": record.machine_reasons,
        "verdict": record.verdict,
        "summary": record.summary,
        "evidence": Jsonb(record.evidence),
        "lesson_for_models": record.lesson_for_models,
        "model": record.model,
    }
    with conn.cursor() as cur:
        cur.execute(_INSERT_SQL, payload)
        row = cur.fetchone()
    conn.commit()
    if not row:
        return None
    return row[0]


def list_post_mortems(
    conn: psycopg.Connection,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_LIST_SQL, (limit,))
        rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        evidence = r["evidence"]
        if isinstance(evidence, str):
            evidence = json.loads(evidence)
        out.append(
            {
                "post_mortem_id": str(r["post_mortem_id"]),
                "post_id": r["post_id"],
                "machine_reasons": list(r["machine_reasons"] or []),
                "verdict": r["verdict"],
                "summary": r["summary"],
                "evidence": evidence or {},
                "lesson_for_models": r["lesson_for_models"],
                "model": r["model"],
                "generated_at": r["generated_at"],
            }
        )
    return out
