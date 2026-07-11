"""Shared Streamlit helpers for validation pipeline dashboard pages."""

from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from config.settings import Settings
from storage.vector_store import create_schema, get_connection
from validation_pipeline.schemas import AccuracyAggregates, PredictionRecord
from validation_pipeline.store import fetch_accuracy_aggregates, list_predictions


def render_accuracy_summary(settings: Settings, *, compact: bool = False) -> Optional[AccuracyAggregates]:
    """Render accuracy metrics and charts. Returns aggregates when DB is available."""
    if not settings.database_url:
        st.warning("DATABASE_URL is not set — accuracy history unavailable.")
        return None

    conn = get_connection(settings)
    try:
        create_schema(conn)
        aggregates = fetch_accuracy_aggregates(conn)
    finally:
        conn.close()

    if aggregates.total_validated == 0:
        st.info("No validated predictions yet. Run collect + predict, then wait for validation.")
        return aggregates

    st.caption("Percentile accuracy")
    cols = st.columns(4)
    cols[0].metric("Validated", aggregates.total_validated)
    cols[1].metric("Percentile MAE", f"{aggregates.mean_absolute_error:.1f}" if aggregates.mean_absolute_error is not None else "—")
    cols[2].metric("Within 10 pts", f"{aggregates.pct_within_10:.0f}%" if aggregates.pct_within_10 is not None else "—")
    cols[3].metric("Mean accuracy", f"{aggregates.mean_accuracy_score:.1f}" if aggregates.mean_accuracy_score is not None else "—")

    st.caption("Count accuracy (likes / comments / shares / total)")
    count_cols = st.columns(5)
    count_cols[0].metric("MAE Likes", f"{aggregates.mae_likes:.1f}" if aggregates.mae_likes is not None else "—")
    count_cols[1].metric("MAE Comments", f"{aggregates.mae_comments:.1f}" if aggregates.mae_comments is not None else "—")
    count_cols[2].metric("MAE Shares", f"{aggregates.mae_shares:.1f}" if aggregates.mae_shares is not None else "—")
    count_cols[3].metric("MAE Total", f"{aggregates.mae_total_engagement:.1f}" if aggregates.mae_total_engagement is not None else "—")
    count_cols[4].metric(
        "Total within 20%",
        f"{aggregates.pct_total_within_20pct:.0f}%" if aggregates.pct_total_within_20pct is not None else "—",
    )

    if not compact and aggregates.time_series:
        df = pd.DataFrame(aggregates.time_series)
        if "day" in df.columns:
            df = df.set_index("day")
        st.subheader("Percentile accuracy over time")
        chart_cols = st.columns(2)
        if "mae" in df.columns:
            chart_cols[0].line_chart(df[["mae"]], height=220)
        if "mean_accuracy" in df.columns:
            chart_cols[1].line_chart(df[["mean_accuracy"]], height=220)

    if not compact and aggregates.mae_likes is not None:
        st.subheader("Count MAE by metric")
        mae_df = pd.DataFrame(
            {
                "metric": ["likes", "comments", "shares", "total"],
                "mae": [
                    aggregates.mae_likes,
                    aggregates.mae_comments,
                    aggregates.mae_shares,
                    aggregates.mae_total_engagement,
                ],
            }
        ).set_index("metric")
        st.bar_chart(mae_df, height=220)

    return aggregates


def render_predictions_table(predictions: list[PredictionRecord]) -> None:
    if not predictions:
        st.info("No predictions to show.")
        return
    rows = []
    for p in predictions:
        rows.append(
            {
                "post_id": p.linkedin_post_id,
                "status": p.status,
                "pred %": round(p.predicted_engagement_percentile, 1),
                "pred likes": p.predicted_likes,
                "pred comments": p.predicted_comments,
                "pred shares": p.predicted_shares,
                "pred total": p.predicted_total_engagement,
                "actual likes": p.actual_likes,
                "actual comments": p.actual_comments,
                "actual shares": p.actual_shares,
                "actual total": p.actual_total_engagement,
                "actual %": round(p.actual_engagement_percentile, 1) if p.actual_engagement_percentile is not None else None,
                "% delta": round(p.prediction_delta, 1) if p.prediction_delta is not None else None,
                "likes Δ": round(p.likes_delta, 1) if p.likes_delta is not None else None,
                "comments Δ": round(p.comments_delta, 1) if p.comments_delta is not None else None,
                "shares Δ": round(p.shares_delta, 1) if p.shares_delta is not None else None,
                "total Δ": round(p.total_engagement_delta, 1) if p.total_engagement_delta is not None else None,
                "due_at": p.validation_due_at.isoformat() if p.validation_due_at else None,
                "validated_at": p.validated_at.isoformat() if p.validated_at else None,
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def load_predictions(settings: Settings, status: str | None = None, limit: int = 100) -> list[PredictionRecord]:
    conn = get_connection(settings)
    try:
        create_schema(conn)
        return list_predictions(conn, status=status, limit=limit)
    finally:
        conn.close()
