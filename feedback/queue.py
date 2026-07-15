"""Async feedback job queue (Phase I.1).

Validate enqueues ``prediction_id``; a separate worker claims and generates
template (+ optional hybrid) feedback. Failures retry until ``max_attempts``,
then dead-letter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

import psycopg

logger = logging.getLogger(__name__)

FeedbackJobStatus = str  # pending | processing | done | dead


@dataclass
class FeedbackJob:
    prediction_id: UUID
    status: str
    attempts: int
    max_attempts: int
    last_error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    claimed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class FeedbackQueueBacklog:
    pending: int = 0
    processing: int = 0
    done: int = 0
    dead: int = 0

    @property
    def open_count(self) -> int:
        return self.pending + self.processing


def enqueue_feedback_job(
    conn: psycopg.Connection,
    prediction_id: UUID,
    *,
    max_attempts: int = 3,
) -> None:
    """Enqueue or re-open a feedback job for a validated prediction."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO feedback_jobs (
                prediction_id, status, attempts, max_attempts
            ) VALUES (%s, 'pending', 0, %s)
            ON CONFLICT (prediction_id) DO UPDATE SET
                status = CASE
                    WHEN feedback_jobs.status IN ('done', 'dead') THEN 'pending'
                    ELSE feedback_jobs.status
                END,
                attempts = CASE
                    WHEN feedback_jobs.status IN ('done', 'dead') THEN 0
                    ELSE feedback_jobs.attempts
                END,
                max_attempts = EXCLUDED.max_attempts,
                last_error = CASE
                    WHEN feedback_jobs.status IN ('done', 'dead') THEN NULL
                    ELSE feedback_jobs.last_error
                END,
                updated_at = now(),
                completed_at = CASE
                    WHEN feedback_jobs.status IN ('done', 'dead') THEN NULL
                    ELSE feedback_jobs.completed_at
                END
            """,
            (prediction_id, max(1, int(max_attempts))),
        )
    conn.commit()


def claim_feedback_jobs(
    conn: psycopg.Connection,
    *,
    limit: int = 20,
) -> list[UUID]:
    """Claim up to ``limit`` pending jobs (SKIP LOCKED). Returns prediction ids."""
    if limit <= 0:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE feedback_jobs
            SET status = 'processing',
                claimed_at = now(),
                attempts = attempts + 1,
                updated_at = now()
            WHERE prediction_id IN (
                SELECT prediction_id
                FROM feedback_jobs
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            RETURNING prediction_id
            """,
            (limit,),
        )
        rows = cur.fetchall()
    conn.commit()
    return [row[0] for row in rows]


def mark_feedback_job_done(
    conn: psycopg.Connection,
    prediction_id: UUID,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE feedback_jobs
            SET status = 'done',
                last_error = NULL,
                completed_at = now(),
                updated_at = now()
            WHERE prediction_id = %s
            """,
            (prediction_id,),
        )
    conn.commit()


def mark_feedback_job_failed(
    conn: psycopg.Connection,
    prediction_id: UUID,
    error: str,
) -> str:
    """Record failure; re-queue as pending or dead-letter. Returns new status."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE feedback_jobs
            SET status = CASE
                    WHEN attempts >= max_attempts THEN 'dead'
                    ELSE 'pending'
                END,
                last_error = %s,
                updated_at = now(),
                completed_at = CASE
                    WHEN attempts >= max_attempts THEN now()
                    ELSE NULL
                END
            WHERE prediction_id = %s
            RETURNING status
            """,
            (error[:2000], prediction_id),
        )
        row = cur.fetchone()
    conn.commit()
    return str(row[0]) if row else "dead"


def count_feedback_queue_backlog(conn: psycopg.Connection) -> FeedbackQueueBacklog:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, COUNT(*)::INTEGER
            FROM feedback_jobs
            GROUP BY status
            """
        )
        counts = {str(status): int(count) for status, count in cur.fetchall()}
    return FeedbackQueueBacklog(
        pending=counts.get("pending", 0),
        processing=counts.get("processing", 0),
        done=counts.get("done", 0),
        dead=counts.get("dead", 0),
    )
