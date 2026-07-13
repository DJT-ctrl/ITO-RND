"""Streamlit views for Phase E feedback-loop observability."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config.settings import Settings
from feedback.dashboard_queries import fetch_learning_status, list_cluster_accuracy
from storage.vector_store import create_schema, get_connection


def render_learning_status(settings: Settings) -> None:
    """Show whether each learning mechanism is active and sufficiently gated."""
    conn = get_connection(settings)
    try:
        create_schema(conn)
        status = fetch_learning_status(conn)
    finally:
        conn.close()

    calibration_ready = status.n_validated >= settings.validation_calibration_n_min
    calibration_active = settings.validation_calibration_enabled and calibration_ready
    injection_active = settings.validation_feedback_injection_enabled
    refreshed = (
        status.last_cluster_refresh_at.strftime("%Y-%m-%d %H:%M UTC")
        if status.last_cluster_refresh_at
        else "never"
    )

    st.subheader("Learning active?")
    columns = st.columns(4)
    columns[0].metric("Validated N", status.n_validated)
    columns[1].metric(
        "Calibration",
        "active" if calibration_active else "inactive",
        help=(
            f"Flag={'on' if settings.validation_calibration_enabled else 'off'}; "
            f"gate={status.n_validated}/{settings.validation_calibration_n_min}."
        ),
    )
    columns[2].metric(
        "Prompt injection",
        "active" if injection_active else "inactive",
    )
    columns[3].metric("Cluster refresh", refreshed)

    if settings.validation_calibration_enabled and not calibration_ready:
        st.warning(
            "Calibration is enabled but the sample gate is closed; "
            "new predictions remain raw."
        )
    elif calibration_active:
        st.success("Calibration is enabled and the global sample gate is open.")
    else:
        st.info("Calibration is in monitor-only mode; raw scores remain user-facing.")


def render_cluster_accuracy(settings: Settings) -> None:
    """Render raw and calibrated MAE by deterministic metadata cluster."""
    conn = get_connection(settings)
    try:
        create_schema(conn)
        rows = list_cluster_accuracy(conn)
    finally:
        conn.close()

    st.subheader("Per-cluster percentile accuracy")
    if not rows:
        st.info("No validated cluster accuracy is available yet.")
        return

    frame = pd.DataFrame(
        [
            {
                "cluster_id": row.cluster_id,
                "N": row.sample_count,
                "live MAE": row.mae,
                "raw MAE": row.raw_mae,
                "calibrated MAE": row.calibrated_mae,
                "within 10 pts": row.pct_within_10,
            }
            for row in rows
        ]
    )
    st.dataframe(frame, use_container_width=True, hide_index=True)
