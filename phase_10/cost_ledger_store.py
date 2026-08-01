"""Postgres CRUD for agentic cost ledger (T10.9)."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timezone
from typing import Literal

import psycopg

Provider = Literal["apify", "gemini"]


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def agentic_context(job_id: str) -> str:
    """Apify/telemetry context tag for agentic attribution."""
    return f"agentic:{job_id}"


def record_spend(
    conn: psycopg.Connection,
    *,
    provider: Provider,
    job_id: str,
    cost_usd: float,
    day: date | None = None,
) -> None:
    """Add cost to the (day, provider, job_id) rollup row."""
    if cost_usd < 0:
        raise ValueError("cost_usd must be >= 0")
    if cost_usd == 0:
        return
    day = day or _utc_today()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agentic_cost_ledger (day, provider, job_id, cost_usd, updated_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (day, provider, job_id) DO UPDATE SET
                cost_usd = agentic_cost_ledger.cost_usd + EXCLUDED.cost_usd,
                updated_at = now()
            """,
            (day, provider, job_id, float(cost_usd)),
        )
    conn.commit()


def sum_spend(
    conn: psycopg.Connection,
    *,
    provider: Provider,
    day: date | None = None,
) -> float:
    """Total USD spent for provider on a UTC calendar day."""
    day = day or _utc_today()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(SUM(cost_usd), 0)
            FROM agentic_cost_ledger
            WHERE provider = %s AND day = %s
            """,
            (provider, day),
        )
        row = cur.fetchone()
    return float(row[0]) if row else 0.0


def sum_spend_month(
    conn: psycopg.Connection,
    *,
    provider: Provider,
    day: date | None = None,
) -> float:
    """Total USD spent for provider in the UTC calendar month of ``day``."""
    day = day or _utc_today()
    month_start = day.replace(day=1)
    last = calendar.monthrange(day.year, day.month)[1]
    month_end = day.replace(day=last)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(SUM(cost_usd), 0)
            FROM agentic_cost_ledger
            WHERE provider = %s AND day >= %s AND day <= %s
            """,
            (provider, month_start, month_end),
        )
        row = cur.fetchone()
    return float(row[0]) if row else 0.0
