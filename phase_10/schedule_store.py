"""Postgres CRUD for agentic job run state (T10.3)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg

from phase_10.models import JOB_FLAG_KEYS, JobRunStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def ensure_job_rows(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for job_id in JOB_FLAG_KEYS:
            cur.execute(
                """
                INSERT INTO agentic_job_runs (job_id, updated_at)
                VALUES (%s, now())
                ON CONFLICT (job_id) DO NOTHING
                """,
                (job_id,),
            )
    conn.commit()


def load_run_rows(conn: psycopg.Connection) -> dict[str, dict[str, Any]]:
    ensure_job_rows(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT job_id, last_run_at, next_run_at, last_result FROM agentic_job_runs"
        )
        return {
            str(job_id): {
                "last_run_at": last_run_at,
                "next_run_at": next_run_at,
                "last_result": last_result,
            }
            for job_id, last_run_at, next_run_at, last_result in cur.fetchall()
        }


def upsert_run(
    conn: psycopg.Connection,
    *,
    job_id: str,
    last_run_at: datetime | None = None,
    next_run_at: datetime | None = None,
    last_result: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agentic_job_runs (
                job_id, last_run_at, next_run_at, last_result, updated_at
            )
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (job_id) DO UPDATE SET
                last_run_at = COALESCE(EXCLUDED.last_run_at, agentic_job_runs.last_run_at),
                next_run_at = COALESCE(EXCLUDED.next_run_at, agentic_job_runs.next_run_at),
                last_result = COALESCE(EXCLUDED.last_result, agentic_job_runs.last_result),
                updated_at = now()
            """,
            (job_id, last_run_at, next_run_at, last_result),
        )
    conn.commit()


def row_to_status(
    job_id: str,
    *,
    label: str,
    enabled: bool,
    row: dict[str, Any] | None,
) -> JobRunStatus:
    row = row or {}
    return JobRunStatus(
        job_id=job_id,
        label=label,
        enabled=enabled,
        last_run_at=_iso(row.get("last_run_at")),
        next_run_at=_iso(row.get("next_run_at")),
        last_result=row.get("last_result"),
    )
