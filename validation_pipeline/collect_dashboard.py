"""Page-open-safe Collect dashboard snapshot (Lane A progress).

Does not load the full corpus or run schema migrations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import psycopg

from config.settings import Settings, load_settings, pydantic_ai_gemini_model
from validation_pipeline.collect_inventory import (
    DatasetInventoryRow,
    build_dataset_inventory_and_unique,
)


@dataclass(frozen=True)
class LaneACoverageStats:
    """DB-only Lane A coverage for Collect page open (no post-id list required)."""

    same_age_total: int = 0
    same_age_validated: int = 0
    same_age_failed: int = 0
    same_age_scheduled: int = 0
    lane_b_scheduled: int = 0
    age_bucket_counts: dict[str, int] = field(default_factory=dict)
    recent_same_age_created: int = 0


def fetch_lane_a_coverage_stats(conn: psycopg.Connection) -> LaneACoverageStats:
    """Aggregate Lane A / Lane B waiting counts without loading corpus posts.

    Sets ``statement_timeout`` for the session. Does **not** call create_schema.
    """
    from validation_pipeline.age_buckets import bucket_for_hours

    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '8000'")

        cur.execute(
            """
            SELECT
                COUNT(DISTINCT linkedin_post_id) FILTER (
                    WHERE prediction_lane = 'same_age'
                ) AS same_age_total,
                COUNT(DISTINCT linkedin_post_id) FILTER (
                    WHERE prediction_lane = 'same_age' AND status = 'validated'
                ) AS same_age_validated,
                COUNT(DISTINCT linkedin_post_id) FILTER (
                    WHERE prediction_lane = 'same_age' AND status = 'failed'
                ) AS same_age_failed,
                COUNT(DISTINCT linkedin_post_id) FILTER (
                    WHERE prediction_lane = 'same_age' AND status = 'scheduled'
                ) AS same_age_scheduled,
                COUNT(*) FILTER (
                    WHERE prediction_lane = 'fixed_horizon' AND status = 'scheduled'
                ) AS lane_b_scheduled,
                COUNT(*) FILTER (
                    WHERE prediction_lane = 'same_age'
                      AND created_at >= NOW() - INTERVAL '24 hours'
                ) AS recent_same_age_created
            FROM predictions
            """
        )
        row = cur.fetchone()
        (
            same_age_total,
            same_age_validated,
            same_age_failed,
            same_age_scheduled,
            lane_b_scheduled,
            recent_same_age_created,
        ) = (int(v or 0) for v in row)

        cur.execute(
            """
            SELECT
                COALESCE(prediction_telemetry->>'age_bucket', '') AS age_bucket,
                prediction_horizon_hours,
                COUNT(*) AS n
            FROM predictions
            WHERE prediction_lane = 'same_age'
            GROUP BY 1, 2
            """
        )
        age_bucket_counts: dict[str, int] = {}
        for bucket_raw, horizon, n in cur.fetchall():
            bucket = (bucket_raw or "").strip()
            if not bucket:
                bucket = bucket_for_hours(
                    float(horizon) if horizon is not None else None
                )
            age_bucket_counts[bucket] = age_bucket_counts.get(bucket, 0) + int(n or 0)

    return LaneACoverageStats(
        same_age_total=same_age_total,
        same_age_validated=same_age_validated,
        same_age_failed=same_age_failed,
        same_age_scheduled=same_age_scheduled,
        lane_b_scheduled=lane_b_scheduled,
        age_bucket_counts=age_bucket_counts,
        recent_same_age_created=recent_same_age_created,
    )


@dataclass(frozen=True)
class CollectDashboardSnapshot:
    """Combined file + DB view for the Collect and predict page."""

    datasets: list[DatasetInventoryRow] = field(default_factory=list)
    corpus_unique: int = 0
    predicted_lane_a: int = 0
    remaining_lane_a: int = 0
    same_age_validated: int = 0
    same_age_failed: int = 0
    lane_b_scheduled: int = 0
    age_bucket_counts: dict[str, int] = field(default_factory=dict)
    predicted_last_24h: int = 0
    lane_a_only: bool = True
    model_name: str = ""
    max_predicts_per_run: int = 2000
    database_available: bool = False
    vector_sum: int = 0


def build_collect_dashboard_snapshot(
    settings: Settings | None = None,
) -> CollectDashboardSnapshot:
    """Discover vectorized datasets + Lane A DB stats without loading posts."""
    from validation_pipeline.vectorized_corpus import discover_vectorized_datasets

    settings = settings or load_settings()
    datasets = discover_vectorized_datasets(settings)
    inventory, corpus_unique = build_dataset_inventory_and_unique(datasets)
    vector_sum = sum(row.vector_count for row in inventory)

    lane_a = LaneACoverageStats()
    database_available = bool(settings.database_url)
    if database_available:
        from storage.vector_store import get_connection

        conn = get_connection(settings)
        try:
            lane_a = fetch_lane_a_coverage_stats(conn)
        except Exception:
            # Page must still render when DB is down or schema lags.
            database_available = False
            lane_a = LaneACoverageStats()
        finally:
            conn.close()

    predicted = lane_a.same_age_total
    remaining = max(0, corpus_unique - predicted) if corpus_unique else 0
    # Lane A-only UI when fixed-horizon (Lane B) predicts/rescrapes are disabled.
    lane_a_only = not bool(getattr(settings, "validation_fixed_horizon_enabled", True))

    return CollectDashboardSnapshot(
        datasets=inventory,
        corpus_unique=corpus_unique,
        predicted_lane_a=predicted,
        remaining_lane_a=remaining,
        same_age_validated=lane_a.same_age_validated,
        same_age_failed=lane_a.same_age_failed,
        lane_b_scheduled=lane_a.lane_b_scheduled,
        age_bucket_counts=dict(lane_a.age_bucket_counts),
        predicted_last_24h=lane_a.recent_same_age_created,
        lane_a_only=lane_a_only,
        model_name=pydantic_ai_gemini_model(),
        max_predicts_per_run=int(
            getattr(settings, "validation_multi_horizon_max_predicts_per_run", 2000)
            or 2000
        ),
        database_available=database_available,
        vector_sum=vector_sum,
    )
