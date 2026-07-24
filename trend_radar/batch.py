"""Offline weekly batch for A2 trend radar."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

from config.settings import Settings
from trend_radar.clustering import (
    cluster_posts,
    match_clusters_to_previous,
    monday_on_or_before,
    week_window,
)
from trend_radar.labels import label_cluster
from trend_radar.schemas import TrendRow
from trend_radar.store import (
    fetch_corpus_posts_in_window,
    fetch_previous_centroids,
    upsert_trend_rows,
)
from storage.vector_store import create_schema, get_connection

logger = logging.getLogger(__name__)


@dataclass
class TrendRadarBatchResult:
    week_start: date
    posts_in_window: int = 0
    clusters_written: int = 0
    dry_run: bool = False
    notes: list[str] = field(default_factory=list)


def run_trend_radar_batch(
    settings: Settings,
    *,
    week: Optional[date] = None,
    dry_run: bool = False,
    skip_llm_labels: bool = False,
    model: Optional[Any] = None,
) -> TrendRadarBatchResult:
    """Cluster clean corpus posts for a week and upsert `trends` rows.

    Uses ``inserted_at`` as the time axis (posts table has no ``posted_at``).
    """
    if not settings.database_url:
        raise ValueError("DATABASE_URL is not set")

    week_start = monday_on_or_before(week or datetime.now(timezone.utc).date())
    # Default to the last *completed* Monday week when caller passes nothing
    # and today is mid-week: still use current week's Monday window so ops
    # can re-run; document in CLI.
    this_start, this_end, _prev_start, _prev_end = week_window(week_start)
    result = TrendRadarBatchResult(week_start=week_start, dry_run=dry_run)

    with get_connection(settings) as conn:
        create_schema(conn)
        posts = fetch_corpus_posts_in_window(conn, this_start, this_end)
        result.posts_in_window = len(posts)
        if len(posts) < 5:
            result.notes.append("Not enough clean posts in window (need ≥5).")
            return result

        snapshots = cluster_posts(posts)
        if not snapshots:
            result.notes.append("No clusters met the minimum size.")
            return result

        prev_week = date.fromordinal(week_start.toordinal() - 7)
        previous = fetch_previous_centroids(conn, week_start=prev_week)
        snapshots = match_clusters_to_previous(snapshots, previous)

        if dry_run:
            result.clusters_written = len(snapshots)
            result.notes.append(
                f"dry_run clusters={len(snapshots)} "
                f"prev_matched_candidates={len(previous)}"
            )
            return result

        rows: list[TrendRow] = []
        for snap in snapshots:
            if skip_llm_labels:
                from trend_radar.clustering import keyword_fallback_label

                label = keyword_fallback_label(snap)
            else:
                label = label_cluster(snap, model=model)
            rows.append(
                TrendRow(
                    week_start=week_start,
                    cluster_id=snap.cluster_id,
                    label=label,
                    post_count=snap.post_count,
                    share_of_corpus=snap.share_of_corpus,
                    growth_rate=snap.growth_rate,
                    mean_total_engagement=snap.mean_total_engagement,
                    example_post_ids=snap.example_post_ids,
                    centroid=snap.centroid.astype(float).tolist(),
                )
            )
        result.clusters_written = upsert_trend_rows(conn, rows)
    return result
