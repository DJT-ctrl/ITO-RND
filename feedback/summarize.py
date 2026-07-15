"""Template cluster roll-up summaries for injection (Phase I.2 / advanced)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import psycopg

from feedback.routing import cluster_label


def build_rollup_summary_text(
    cluster_id: str,
    *,
    sample_count: int,
    mean_delta: Optional[float],
    std_delta: Optional[float] = None,
) -> str:
    """Deterministic one-paragraph roll-up from cluster stats (no LLM)."""
    label = cluster_label(cluster_id)
    n = max(0, int(sample_count))
    if mean_delta is None:
        return (
            f"Cluster `{cluster_id}` ({label}): N={n} validated lessons; "
            f"mean prediction bias not yet available."
        )
    md = float(mean_delta)
    if md > 1.0:
        direction = "underestimates"
        hint = "Bias similar posts upward vs neighbors."
    elif md < -1.0:
        direction = "overestimates"
        hint = "Bias similar posts downward vs neighbors."
    else:
        direction = "is roughly calibrated"
        hint = "Small residual bias; treat lessons as qualitative."
    std_part = ""
    if std_delta is not None:
        std_part = f" std_delta={float(std_delta):+.1f}."
    return (
        f"Cluster `{cluster_id}` ({label}): N={n}; mean_delta={md:+.1f} "
        f"(model typically {direction}).{std_part} {hint}"
    )


def structured_bias_line(
    *,
    mean_delta: Optional[float],
    sample_count: int = 0,
) -> str:
    """Grounded JSON-ish bias hint for the prompt (numbers only)."""
    if mean_delta is None:
        return (
            'Structured bias: {"cluster_mean_delta": null, "direction": "unknown", '
            f'"N": {int(sample_count)}}}'
        )
    md = float(mean_delta)
    if md > 1.0:
        direction = "underestimated"
    elif md < -1.0:
        direction = "overestimated"
    else:
        direction = "accurate"
    return (
        "Structured bias: "
        f'{{"cluster_mean_delta": {md:.2f}, "direction": "{direction}", '
        f'"N": {int(sample_count)}}}'
    )


def refresh_cluster_rollups(conn: psycopg.Connection) -> int:
    """Write ``rollup_summary`` for every prediction_clusters row. Returns count."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cluster_id, sample_count, mean_delta, std_delta
            FROM prediction_clusters
            """
        )
        rows = cur.fetchall()
        now = datetime.now(timezone.utc)
        for cluster_id, sample_count, mean_delta, std_delta in rows:
            summary = build_rollup_summary_text(
                str(cluster_id),
                sample_count=int(sample_count or 0),
                mean_delta=float(mean_delta) if mean_delta is not None else None,
                std_delta=float(std_delta) if std_delta is not None else None,
            )
            cur.execute(
                """
                UPDATE prediction_clusters
                SET rollup_summary = %s,
                    rollup_updated_at = %s
                WHERE cluster_id = %s
                """,
                (summary, now, cluster_id),
            )
    conn.commit()
    return len(rows)


def fetch_cluster_rollup(
    conn: psycopg.Connection,
    cluster_id: str,
) -> tuple[Optional[str], Optional[float], int]:
    """Return (rollup_summary, mean_delta, sample_count) for a cluster."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rollup_summary, mean_delta, sample_count
            FROM prediction_clusters
            WHERE cluster_id = %s
            """,
            (cluster_id,),
        )
        row = cur.fetchone()
    if not row:
        return None, None, 0
    summary = str(row[0]) if row[0] else None
    mean_delta = float(row[1]) if row[1] is not None else None
    sample_count = int(row[2] or 0)
    return summary, mean_delta, sample_count
