"""Offline metadata vs embedding-centroid routing MAE comparison (Phase H)."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Literal, Optional, Sequence
from uuid import UUID

from pydantic import BaseModel, Field

from feedback.routing import assign_cluster_id, metadata_cluster_id

RoutingMode = Literal["metadata", "centroid"]


class RoutingReplayRow(BaseModel):
    prediction_id: UUID
    actual_percentile: float
    raw_percentile: float
    content: str = ""
    follower_count: Optional[int] = None
    embedding: Optional[list[float]] = None


class RoutingModeMetrics(BaseModel):
    mode: RoutingMode
    sample_count: int
    mae: float
    pct_within_10: float
    per_cluster_mae: dict[str, float] = Field(default_factory=dict)
    rows_with_embedding: int = 0
    rows_routed_via_centroid: int = 0


class RoutingMaeReport(BaseModel):
    schema_version: str = "1.0"
    generated_at: datetime
    total_rows: int
    training_rows: int
    holdout_rows: int
    centroid_count: int
    modes: list[RoutingModeMetrics]
    notes: list[str] = Field(default_factory=list)


def run_routing_mae_replay(
    rows: Sequence[RoutingReplayRow],
    centroids: Sequence[tuple[str, Sequence[float]]],
    *,
    holdout_size: int = 30,
    n_min: int = 30,
) -> RoutingMaeReport:
    """Compare holdout MAE when cluster offsets use metadata vs centroid routing.

    Training stats (mean_delta per cluster) are learned only from non-holdout rows,
    using the same routing mode under test. Holdout is stable-hash selected.
    """
    if holdout_size < 1:
        raise ValueError("holdout_size must be at least 1")
    if len(rows) <= holdout_size:
        raise ValueError(
            f"Need more than {holdout_size} validated rows; found {len(rows)}"
        )

    ordered = sorted(rows, key=lambda row: _stable_key(row.prediction_id))
    holdout = ordered[:holdout_size]
    training = ordered[holdout_size:]
    centroid_list = list(centroids)

    modes = [
        _evaluate_mode(
            "metadata",
            training,
            holdout,
            centroids=[],
            n_min=n_min,
        ),
        _evaluate_mode(
            "centroid",
            training,
            holdout,
            centroids=centroid_list,
            n_min=n_min,
        ),
    ]
    return RoutingMaeReport(
        generated_at=datetime.now(timezone.utc),
        total_rows=len(rows),
        training_rows=len(training),
        holdout_rows=len(holdout),
        centroid_count=len(centroid_list),
        modes=modes,
        notes=[
            "Holdout rows are excluded from per-cluster mean_delta training.",
            (
                "Centroid mode falls back to metadata when embedding or centroids "
                "are missing for a row."
            ),
            (
                "MAE uses cluster mean_delta calibration offset when training N "
                f">= {n_min} for that cluster; otherwise raw score."
            ),
        ],
    )


def _evaluate_mode(
    mode: RoutingMode,
    training: Sequence[RoutingReplayRow],
    holdout: Sequence[RoutingReplayRow],
    *,
    centroids: Sequence[tuple[str, Sequence[float]]],
    n_min: int,
) -> RoutingModeMetrics:
    use_centroids = mode == "centroid" and bool(centroids)
    cluster_deltas: dict[str, list[float]] = defaultdict(list)
    for row in training:
        cluster_id = _route(row, use_centroids=use_centroids, centroids=centroids)
        cluster_deltas[cluster_id].append(row.actual_percentile - row.raw_percentile)

    errors: list[float] = []
    cluster_errors: dict[str, list[float]] = defaultdict(list)
    with_embedding = 0
    via_centroid = 0
    for row in holdout:
        if row.embedding:
            with_embedding += 1
        cluster_id = _route(row, use_centroids=use_centroids, centroids=centroids)
        if use_centroids and row.embedding and centroids:
            metadata_id = metadata_cluster_id(row.content, row.follower_count)
            if cluster_id != metadata_id:
                via_centroid += 1
        deltas = cluster_deltas.get(cluster_id, [])
        if len(deltas) >= n_min:
            score = min(100.0, max(0.0, row.raw_percentile + mean(deltas)))
        else:
            score = row.raw_percentile
        error = abs(row.actual_percentile - score)
        errors.append(error)
        cluster_errors[cluster_id].append(error)

    return RoutingModeMetrics(
        mode=mode,
        sample_count=len(errors),
        mae=round(mean(errors), 4) if errors else 0.0,
        pct_within_10=round(
            sum(error <= 10 for error in errors) / len(errors) * 100,
            2,
        )
        if errors
        else 0.0,
        per_cluster_mae={
            cluster_id: round(mean(values), 4)
            for cluster_id, values in sorted(cluster_errors.items())
        },
        rows_with_embedding=with_embedding,
        rows_routed_via_centroid=via_centroid,
    )


def _route(
    row: RoutingReplayRow,
    *,
    use_centroids: bool,
    centroids: Sequence[tuple[str, Sequence[float]]],
) -> str:
    if use_centroids:
        return assign_cluster_id(
            row.content,
            row.follower_count,
            embedding=row.embedding,
            centroids=centroids,
        )
    return metadata_cluster_id(row.content, row.follower_count)


def _stable_key(prediction_id: UUID) -> str:
    return hashlib.sha256(str(prediction_id).encode("utf-8")).hexdigest()
