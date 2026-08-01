"""CLI: compare metadata vs centroid routing MAE; save telemetry JSON."""

from __future__ import annotations

import argparse
import json
import logging
from typing import Optional
from uuid import UUID

import psycopg

from config.paths import resolve_data_path, utc_artifact_stamp
from config.settings import load_settings
from feedback.generate import FEEDBACK_VERSION
from feedback.routing_mae import RoutingReplayRow, run_routing_mae_replay
from feedback.store import embedding_to_float_list, fetch_cluster_centroids
from storage.vector_store import create_schema, get_connection

logger = logging.getLogger(__name__)


def fetch_routing_replay_rows(conn: psycopg.Connection) -> list[RoutingReplayRow]:
    """Load validated rows with content + optional embedding for routing compare."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                p.prediction_id,
                p.actual_engagement_percentile,
                COALESCE(
                    (p.prediction_telemetry->>'raw_percentile')::DOUBLE PRECISION,
                    p.predicted_engagement_percentile
                ) AS raw_percentile,
                COALESCE(p.content, '') AS content,
                NULLIF(
                    (p.prediction_telemetry->>'follower_count')::INT,
                    NULL
                ) AS follower_count,
                p.embedding
            FROM predictions p
            WHERE p.status = 'validated'
              AND p.actual_engagement_percentile IS NOT NULL
              AND p.predicted_engagement_percentile IS NOT NULL
            ORDER BY p.prediction_id
            """
        )
        rows = cur.fetchall()
    result: list[RoutingReplayRow] = []
    for row in rows:
        embedding = row[5]
        vector: Optional[list[float]] = None
        if embedding is not None:
            vector = embedding_to_float_list(embedding)
        result.append(
            RoutingReplayRow(
                prediction_id=row[0] if isinstance(row[0], UUID) else UUID(str(row[0])),
                actual_percentile=float(row[1]),
                raw_percentile=float(row[2]),
                content=str(row[3] or ""),
                follower_count=int(row[4]) if row[4] is not None else None,
                embedding=vector,
            )
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout-size", type=int, default=30)
    parser.add_argument(
        "--n-min",
        type=int,
        default=30,
        help="Min training rows per cluster before applying mean_delta offset.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    settings = load_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is not set.")

    conn = get_connection(settings)
    try:
        create_schema(conn)
        rows = fetch_routing_replay_rows(conn)
        centroids = fetch_cluster_centroids(conn)
    finally:
        conn.close()

    try:
        report = run_routing_mae_replay(
            rows,
            centroids,
            holdout_size=args.holdout_size,
            n_min=args.n_min,
        )
    except ValueError as exc:
        raise SystemExit(f"Routing MAE report not run: {exc}") from exc

    output_dir = resolve_data_path(settings.telemetry_data_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"routing_mae_{utc_artifact_stamp()}.json"
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    for mode in report.modes:
        print(
            f"{mode.mode}: mae={mode.mae} pct_within_10={mode.pct_within_10} "
            f"via_centroid={mode.rows_routed_via_centroid}/{mode.sample_count}"
        )
    print(f"Saved routing MAE report ({FEEDBACK_VERSION} context) path={path}")


if __name__ == "__main__":
    main()
