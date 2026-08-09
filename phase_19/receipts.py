"""Receipt helpers for Phase 19 collection outcomes."""

from __future__ import annotations

from typing import Any

import psycopg

from phase_19 import evidence_store


def write_receipt(
    conn: psycopg.Connection,
    *,
    subscriber_id: str,
    collection_job_id: str,
    collected_count: int,
    rejected_count: int,
    actual_cost_usd: float,
    coverage_gaps: list[str],
    summary: str,
    next_refresh_hours: float = 24.0,
) -> dict[str, Any]:
    """Persist a subscriber-visible evidence receipt for one collection job."""
    return evidence_store.save_receipt(
        conn,
        subscriber_id=subscriber_id,
        collection_job_id=collection_job_id,
        collected_count=collected_count,
        rejected_count=rejected_count,
        actual_cost_usd=actual_cost_usd,
        coverage_gaps=coverage_gaps,
        summary=summary,
        next_refresh_hours=next_refresh_hours,
    )
