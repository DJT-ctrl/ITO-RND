"""Streamlit helpers for the feedback-loop dashboard page."""

from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from config.settings import Settings
from feedback.batch import (
    generate_feedback_for_prediction_id,
    run_feedback_batch,
)
from feedback.calibration import apply_calibration
from feedback.generate import FEEDBACK_VERSION
from feedback.schemas import CalibrationStats, ClusterStats, FeedbackRecord
from feedback.store import (
    count_feedback_coverage,
    fetch_calibration_stats,
    list_clusters,
    list_recent_feedback,
    refresh_cluster_stats,
)
from storage.vector_store import create_schema, get_connection
from validation_pipeline.store import list_predictions


def render_feedback_settings_panel(settings: Settings) -> None:
    """Show current feature flags so operators know what is active."""
    st.subheader("Feedback loop settings")
    cols = st.columns(4)
    cols[0].metric(
        "Calibration",
        "ON" if settings.validation_calibration_enabled else "OFF",
    )
    cols[1].metric(
        "Feedback records",
        "ON" if settings.validation_feedback_enabled else "OFF",
    )
    cols[2].metric(
        "Prompt injection",
        "ON" if settings.validation_feedback_injection_enabled else "OFF",
    )
    cols[3].metric("Injection limit", settings.validation_feedback_injection_limit)

    st.caption(
        f"Global N_min = **{settings.validation_calibration_n_min}** · "
        f"Cluster N_min = **{settings.validation_cluster_n_min}** · "
        f"Toggle via env: `VALIDATION_CALIBRATION_ENABLED`, "
        f"`VALIDATION_FEEDBACK_ENABLED`, `VALIDATION_FEEDBACK_INJECTION_ENABLED`."
    )


def render_calibration_panel(settings: Settings) -> Optional[CalibrationStats]:
    """Global mean_delta and whether the N_min gate would apply."""
    st.subheader("Calibration (global)")
    conn = get_connection(settings)
    try:
        create_schema(conn)
        stats = fetch_calibration_stats(conn)
    finally:
        conn.close()

    n_min = settings.validation_calibration_n_min
    would_apply = (
        settings.validation_calibration_enabled
        and stats.n_validated >= n_min
    )
    demo_raw = 70.0
    demo = apply_calibration(demo_raw, stats.mean_delta, stats.n_validated, n_min)

    cols = st.columns(5)
    cols[0].metric("Validated (N)", stats.n_validated)
    cols[1].metric("Mean delta", f"{stats.mean_delta:+.2f}")
    cols[2].metric("N_min gate", n_min)
    cols[3].metric("Would apply?", "Yes" if would_apply else "No")
    cols[4].metric(
        "Example (raw 70)",
        f"{demo.calibrated_percentile:.1f}",
        delta=f"{demo.calibrated_percentile - demo_raw:+.1f}" if demo.applied else "unchanged",
    )

    if not settings.validation_calibration_enabled:
        st.info("Calibration is disabled — predictions use raw neighbor percentiles.")
    elif stats.n_validated < n_min:
        st.warning(
            f"Cold start: need **{n_min - stats.n_validated}** more validated rows "
            "before the global offset is applied."
        )
    else:
        direction = (
            "overestimates"
            if stats.mean_delta < 0
            else "underestimates"
            if stats.mean_delta > 0
            else "is unbiased on average"
        )
        st.success(
            f"Global bias: model typically **{direction}** by "
            f"**{abs(stats.mean_delta):.1f}** percentile points "
            f"(formula: `calibrated = clamp(raw + mean_delta, 0, 100)`)."
        )
    return stats


def render_coverage_panel(settings: Settings) -> dict[str, int]:
    """Validated vs feedback coverage metrics."""
    st.subheader("Feedback coverage")
    conn = get_connection(settings)
    try:
        create_schema(conn)
        coverage = count_feedback_coverage(conn, feedback_version=FEEDBACK_VERSION)
    finally:
        conn.close()

    cols = st.columns(3)
    cols[0].metric("Validated predictions", coverage["validated"])
    cols[1].metric("With feedback (v1)", coverage["with_feedback"])
    cols[2].metric("Missing feedback", coverage["missing_feedback"])
    if coverage["missing_feedback"] > 0:
        st.caption(
            "Use **Generate missing feedback** below to backfill template lessons."
        )
    return coverage


def render_clusters_table(settings: Settings, *, cluster_n_min: int) -> list[ClusterStats]:
    """Per-cluster sample counts and mean deltas."""
    st.subheader("Clusters")
    conn = get_connection(settings)
    try:
        create_schema(conn)
        clusters = list_clusters(conn)
    finally:
        conn.close()

    if not clusters:
        st.info(
            "No clusters yet. Generate feedback for validated predictions "
            "(clusters are derived from content length × format × follower band)."
        )
        return []

    rows = []
    for c in clusters:
        eligible = c.sample_count >= cluster_n_min and c.mean_delta is not None
        rows.append(
            {
                "cluster_id": c.cluster_id,
                "label": c.label or "",
                "samples": c.sample_count,
                "mean_delta": round(c.mean_delta, 2) if c.mean_delta is not None else None,
                "std_delta": round(c.std_delta, 2) if c.std_delta is not None else None,
                "cluster calib": "ready" if eligible else f"need {cluster_n_min}",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    return clusters


def render_recent_feedback_table(
    settings: Settings,
    *,
    limit: int = 40,
    cluster_id: Optional[str] = None,
) -> list[FeedbackRecord]:
    """Recent structured feedback lessons."""
    st.subheader("Recent feedback records")
    conn = get_connection(settings)
    try:
        create_schema(conn)
        records = list_recent_feedback(
            conn, limit=limit, cluster_id=cluster_id, feedback_version=FEEDBACK_VERSION
        )
    finally:
        conn.close()

    if not records:
        st.info("No feedback records yet.")
        return []

    rows = []
    for r in records:
        d = r.feedback_json.delta_summary
        lessons = r.feedback_json.lessons_for_similar_posts
        missed = r.feedback_json.what_missed
        rows.append(
            {
                "generated_at": r.generated_at.strftime("%Y-%m-%d %H:%M")
                if r.generated_at
                else "",
                "cluster": r.cluster_id or "",
                "direction": d.direction,
                "pred %": round(d.predicted_percentile, 1),
                "actual %": round(d.actual_percentile, 1),
                "delta": round(d.prediction_delta, 1),
                "lesson": lessons[0] if lessons else "",
                "missed": missed[0] if missed else "",
                "method": r.generation_method,
                "prediction_id": str(r.prediction_id),
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    return records


def render_manual_actions(settings: Settings) -> None:
    """Buttons to run feedback batch, refresh clusters, regenerate one row."""
    st.subheader("Manual process")
    st.caption(
        "Run these when you want to backfill or refresh without waiting for "
        "the next validation worker pass."
    )

    col_a, col_b = st.columns(2)

    with col_a:
        limit = st.number_input(
            "Backfill limit",
            min_value=1,
            max_value=500,
            value=50,
            key="feedback_batch_limit",
        )
        if st.button(
            "Generate missing feedback",
            type="primary",
            disabled=not settings.validation_feedback_enabled,
            help="Template feedback for validated predictions that lack a v1 row.",
        ):
            with st.spinner("Generating template feedback..."):
                batch = run_feedback_batch(settings, limit=int(limit))
            st.session_state["feedback_last_batch"] = batch
            st.rerun()

        if st.button("Refresh cluster stats"):
            with st.spinner("Recomputing cluster mean_delta / sample_count..."):
                conn = get_connection(settings)
                try:
                    create_schema(conn)
                    n = refresh_cluster_stats(conn)
                finally:
                    conn.close()
            st.session_state["feedback_clusters_refreshed"] = n
            st.rerun()

    with col_b:
        st.markdown("**Regenerate one prediction**")
        validated = []
        conn = get_connection(settings)
        try:
            create_schema(conn)
            validated = list_predictions(conn, status="validated", limit=100)
        finally:
            conn.close()

        options = {
            f"{p.linkedin_post_id}  ({p.prediction_delta:+.1f} Δ)"
            if p.prediction_delta is not None
            else p.linkedin_post_id: p.prediction_id
            for p in validated
        }
        if not options:
            st.info("No validated predictions to regenerate.")
        else:
            choice = st.selectbox("Validated prediction", list(options.keys()))
            if st.button("Regenerate feedback for selected"):
                pid = options[choice]
                try:
                    with st.spinner("Regenerating..."):
                        record = generate_feedback_for_prediction_id(pid, settings)
                        conn = get_connection(settings)
                        try:
                            create_schema(conn)
                            refresh_cluster_stats(conn)
                        finally:
                            conn.close()
                    st.session_state["feedback_last_regen"] = str(record.prediction_id)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    if "feedback_last_batch" in st.session_state:
        batch = st.session_state["feedback_last_batch"]
        st.success(
            f"Batch done: processed={batch.processed} · generated={batch.generated} · "
            f"failed={batch.failed} · skipped={batch.skipped}"
        )
    if "feedback_clusters_refreshed" in st.session_state:
        st.success(
            f"Cluster stats refreshed for "
            f"{st.session_state['feedback_clusters_refreshed']} cluster(s)."
        )
    if "feedback_last_regen" in st.session_state:
        st.success(
            f"Regenerated feedback for prediction `{st.session_state['feedback_last_regen']}`."
        )


def render_feedback_detail_expander(records: list[FeedbackRecord]) -> None:
    """Expandable full JSON for a selected feedback row."""
    if not records:
        return
    st.subheader("Inspect feedback JSON")
    labels = {
        f"{r.cluster_id or '—'} · {r.feedback_json.delta_summary.direction} · "
        f"{r.generated_at.strftime('%Y-%m-%d %H:%M') if r.generated_at else '?'}"
        : r
        for r in records
    }
    pick = st.selectbox("Select record", list(labels.keys()), key="feedback_inspect")
    record = labels[pick]
    payload = record.feedback_json
    st.markdown(
        f"**Prediction** `{record.prediction_id}` · "
        f"**Cluster** `{record.cluster_id}` · "
        f"**Method** `{record.generation_method}`"
    )
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**What worked**")
        for item in payload.what_worked or ["—"]:
            st.write(f"- {item}")
        st.markdown("**Lessons**")
        for item in payload.lessons_for_similar_posts or ["—"]:
            st.write(f"- {item}")
    with c2:
        st.markdown("**What missed**")
        for item in payload.what_missed or ["—"]:
            st.write(f"- {item}")
        d = payload.delta_summary
        st.markdown(
            f"**Delta summary:** predicted {d.predicted_percentile:.1f} → "
            f"actual {d.actual_percentile:.1f} "
            f"({d.prediction_delta:+.1f}, {d.direction})"
        )
    with st.expander("Raw JSON"):
        st.json(payload.model_dump(mode="json"))
