"""Streamlit views for Phase E feedback-loop observability."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from config.settings import Settings
from feedback.dashboard_queries import fetch_learning_status, list_cluster_accuracy
from feedback.evaluation import (
    CALIBRATION_LIFT_GATE_PCT,
    FeedbackEvaluationReport,
    PhaseFDecision,
    phase_f_decision,
)
from feedback.evaluation_reports import load_latest_eval_feedback_report
from feedback.evaluation_runner import run_and_save_offline_evaluation
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
    st.caption(
        "Plain English: are we allowed to nudge scores / show lessons right now? "
        "Phase F go/no-go appears below when an offline eval report exists."
    )
    columns = st.columns(4)
    columns[0].metric(
        "Graded posts",
        status.n_validated,
        help="How many predictions have been checked against real engagement.",
    )
    columns[1].metric(
        "Score nudge (calibration)",
        "ON" if calibration_active else "OFF",
        help=(
            f"Phase A · Flag={'on' if settings.validation_calibration_enabled else 'off'}; "
            f"need {settings.validation_calibration_n_min} graded posts "
            f"(have {status.n_validated})."
        ),
    )
    columns[2].metric(
        "Show lessons to AI",
        "ON" if injection_active else "OFF",
        help="Phase D · Prompt injection flag.",
    )
    columns[3].metric(
        "Buckets last refreshed",
        refreshed,
        help="When cluster / bucket stats were last recomputed.",
    )

    if settings.validation_calibration_enabled and not calibration_ready:
        st.warning(
            "Score nudge is enabled but we do not have enough graded posts yet; "
            "predictions stay un-nudged."
        )
    elif calibration_active:
        st.success("Score nudge is enabled and the sample gate is open.")
    else:
        st.info(
            "Score nudge is monitor-only — user-facing scores stay raw "
            "(usual safe default until Phase F is GO)."
        )
    report, path = load_latest_eval_feedback_report(settings)
    if report is not None and path is not None:
        decision = phase_f_decision(report)
        _render_phase_f_status_banner(decision, report, path)


def render_cluster_accuracy(settings: Settings) -> None:
    """Render raw and calibrated MAE by deterministic metadata cluster."""
    conn = get_connection(settings)
    try:
        create_schema(conn)
        rows = list_cluster_accuracy(conn)
    finally:
        conn.close()

    st.subheader("Accuracy by bucket")
    st.caption(
        "Average error (MAE) per length × format × audience bucket. "
        "Lower is better. “Within 10 pts” = share of predictions within 10 "
        "percentile points of reality."
    )
    if not rows:
        st.info("No graded bucket accuracy is available yet.")
        return

    frame = pd.DataFrame(
        [
            {
                "bucket": row.cluster_id,
                "N graded": row.sample_count,
                "avg error (live)": row.mae,
                "avg error (raw)": row.raw_mae,
                "avg error (nudged)": row.calibrated_mae,
                "within 10 pts %": row.pct_within_10,
            }
            for row in rows
        ]
    )
    st.dataframe(frame, use_container_width=True, hide_index=True)


def render_offline_evaluation_panel(
    settings: Settings,
    *,
    holdout_size: int = 30,
) -> None:
    """Run leakage-safe 4-arm replay and show the latest saved report."""
    st.subheader("Offline evaluation (Phase F) — prove it helps")
    st.caption(
        "Held-out replay: compare raw vs nudged scores, with and without lessons. "
        f"Need more than {holdout_size} graded posts (holdout={holdout_size}). "
        f"GO for calibration needs ≥{CALIBRATION_LIFT_GATE_PCT:g}% drop in average "
        "error (MAE) on two stable runs. Soft blend / injection need shadow mode "
        "to beat live."
    )

    conn = get_connection(settings)
    try:
        create_schema(conn)
        status = fetch_learning_status(conn)
    finally:
        conn.close()

    n_validated = status.n_validated
    cols = st.columns(3)
    cols[0].metric("Graded posts", n_validated)
    cols[1].metric("Holdout size", holdout_size)
    cols[2].metric(
        "Ready to run?",
        "yes" if n_validated > holdout_size else "not yet",
    )

    if n_validated <= holdout_size:
        st.warning(
            f"Need more than {holdout_size} validated rows to run holdout={holdout_size}; "
            f"found {n_validated}. Collect and validate more posts first."
        )
    elif st.button(
        "Run offline evaluation",
        type="primary",
        key="run_offline_feedback_evaluation",
        help="Same as: python -m feedback.jobs.run_feedback_evaluation",
    ):
        try:
            report, path = run_and_save_offline_evaluation(
                settings,
                holdout_size=holdout_size,
            )
        except ValueError as exc:
            st.error(f"Evaluation not run: {exc}")
        except Exception as exc:
            st.exception(exc)
        else:
            st.success(
                f"Saved {len(report.arms)} arms "
                f"(holdout={report.holdout_rows}, training={report.training_rows}) "
                f"→ `{path.name}`"
            )
            _render_evaluation_report(report, path)
            return

    report, path = load_latest_eval_feedback_report(settings)
    if report is None or path is None:
        st.info("No eval_feedback_*.json reports yet. Run an evaluation when N is ready.")
        return
    st.markdown(f"**Latest report:** `{path.name}`")
    _render_evaluation_report(report, path)


def _render_phase_f_status_banner(
    decision: PhaseFDecision,
    report: FeedbackEvaluationReport,
    path: Path,
) -> None:
    """Compact Phase F decision strip under Learning active?."""
    lift = decision.calibration_lift_pct
    lift_label = f"{lift:.2f}%" if lift is not None else "n/a"
    if decision.calibration_decision == "GO" and decision.injection_decision == "GO":
        st.success(
            f"Phase F **GO** — calibration lift {lift_label} "
            f"(gate ≥{CALIBRATION_LIFT_GATE_PCT:g}%); shadow beats live. "
            f"Latest: `{path.name}` (N={report.total_rows})."
        )
    elif decision.calibration_decision == "GO":
        st.warning(
            f"Phase F calibration **GO** ({lift_label} ≥ {CALIBRATION_LIFT_GATE_PCT:g}%), "
            f"but soft_blend / injection stay **NO-GO** "
            f"(shadow does not beat live). Latest: `{path.name}`."
        )
    else:
        st.warning(
            f"Phase F **NO-GO** — calibration lift {lift_label} "
            f"(need ≥{CALIBRATION_LIFT_GATE_PCT:g}%); "
            f"soft_blend / injection **NO-GO**. "
            f"Keep shadow ON. Latest: `{path.name}` (N={report.total_rows})."
        )


def _render_evaluation_report(
    report: FeedbackEvaluationReport,
    path: Path,
) -> None:
    decision = phase_f_decision(report)
    _render_phase_f_gates(decision, report)

    summary = st.columns(4)
    summary[0].metric("Holdout", report.holdout_rows)
    summary[1].metric("Training", report.training_rows)
    summary[2].metric("Global mean Δ", f"{report.global_mean_delta:.2f}")
    summary[3].metric(
        "Calibration ready",
        "yes" if report.global_calibration_ready else "no",
    )
    st.caption(
        "Global mean Δ is training bias (actual − predicted), **not** the MAE lift % gate."
    )

    arms_frame = pd.DataFrame(
        [
            {
                "arm": arm.arm,
                "calibration": arm.calibration_enabled,
                "injection": arm.feedback_injection_enabled,
                "pref_version": arm.preferred_feedback_version or "—",
                "N": arm.sample_count,
                "MAE": arm.mae,
                "% within 10": arm.pct_within_10,
            }
            for arm in report.arms
        ]
    )
    st.dataframe(arms_frame, use_container_width=True, hide_index=True)

    pref = getattr(report, "version_preference", None)
    if pref is not None and pref.holdout_rows:
        st.caption(
            f"Holdout lesson preference: approved v2 on "
            f"{pref.holdout_with_approved_v2}/{pref.holdout_rows} "
            f"({pref.preferred_v2_share_pct}%). "
            "D-v1/D-v2 scaffold arms share MAE until Phase J."
        )

    cluster_rows: list[dict] = []
    for arm in report.arms:
        for cluster_id, mae in arm.per_cluster_mae.items():
            cluster_rows.append(
                {
                    "arm": arm.arm,
                    "cluster_id": cluster_id,
                    "MAE": mae,
                }
            )
    if cluster_rows:
        st.caption("Per-cluster MAE (holdout)")
        st.dataframe(
            pd.DataFrame(cluster_rows),
            use_container_width=True,
            hide_index=True,
        )

    for note in report.notes:
        st.caption(note)
    st.caption(f"Report path: `{path}`")


def _render_phase_f_gates(
    decision: PhaseFDecision,
    report: FeedbackEvaluationReport,
) -> None:
    """Show calibration lift and shadow vs live against Phase F ship gates."""
    st.markdown("#### Phase F go / no-go")
    lift = decision.calibration_lift_pct
    lift_label = f"{lift:.2f}%" if lift is not None else "n/a"
    delta = decision.shadow_mae_delta
    delta_label = f"{delta:+.4f}" if delta is not None else "n/a"

    gate_cols = st.columns(4)
    gate_cols[0].metric(
        "Cal MAE lift",
        lift_label,
        delta=f"gate ≥{CALIBRATION_LIFT_GATE_PCT:g}%",
        help=(
            "Improvement of calibrated_no_feedback vs raw_no_feedback on holdout. "
            "Do not confuse with global mean Δ."
        ),
    )
    gate_cols[1].metric(
        "Calibration",
        decision.calibration_decision,
        help=f"GO only when lift ≥ {CALIBRATION_LIFT_GATE_PCT:g}% on two stable runs.",
    )
    gate_cols[2].metric(
        "Shadow sample",
        f"{decision.shadow_sample_count}/{report.holdout_rows}",
        help="Holdout rows with shadow_percentile telemetry.",
    )
    gate_cols[3].metric(
        "Soft blend / injection",
        decision.soft_blend_decision,
        delta=f"live−shadow {delta_label}",
        help="GO only when shadow MAE clearly beats live (positive live−shadow delta).",
    )

    if decision.calibration_decision == "GO":
        st.success(
            f"Calibration gate met ({lift_label} ≥ {CALIBRATION_LIFT_GATE_PCT:g}%). "
            "Confirm with a second identical run before flipping the flag."
        )
    else:
        st.error(
            f"Calibration **NO-GO**: lift {lift_label} < {CALIBRATION_LIFT_GATE_PCT:g}% gate. "
            "Keep `VALIDATION_CALIBRATION_ENABLED=false`."
        )

    if decision.shadow_sample_count == 0:
        st.info(
            "No shadow telemetry in this holdout yet. Keep "
            "`VALIDATION_SHADOW_MODE_ENABLED=true` and collect more predicts."
        )
    elif decision.shadow_beats_live:
        st.success(
            f"Shadow beats live (MAE delta {delta_label}). "
            "Soft blend / injection candidates for a second look."
        )
    else:
        st.warning(
            f"Shadow does **not** beat live (MAE delta {delta_label}). "
            "Keep `hard_lock` and injection OFF; continue collecting shadow."
        )
