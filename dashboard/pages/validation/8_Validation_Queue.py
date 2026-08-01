"""Validation Pipeline — queue, comparison view, and selected re-scrapes."""

import sys
from pathlib import Path
from uuid import UUID

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from config.settings import load_settings  # noqa: E402
from dashboard.chrome import page_header, pipeline_flow_strip, render_phase_badges, section_header  # noqa: E402
from validation_pipeline.ui import (  # noqa: E402
    load_predictions,
    render_validation_batch_summary,
    render_validation_comparison_table,
)
from validation_pipeline.worker import run_due_validations, run_validations_for_ids  # noqa: E402

st.set_page_config(page_title="Validation queue", layout="wide")
page_header(
    "Validation queue",
    "Compare what we predicted against what actually happened (likes, comments, "
    "shares). Re-scrape LinkedIn when due, or force-validate for backtests. "
    "After grading, lessons are written automatically — manage them on "
    "**Feedback loop**.",
    step_hint="Validation step 2 of 4 · Previous: Collect and predict · Next: Accuracy over time",
)
pipeline_flow_strip("validation", "queue")
render_phase_badges(["0", "B"])

section_header(
    "How grading works",
    """
**Baseline (T0)** = engagement when we first saw the post.
**Predicted** = model forecast.
**Actual** = engagement after re-scrape (or known actuals in backtest).

Use the sidebar to run due validations or force-validate selected rows.
""",
)

settings = load_settings()

if not settings.database_url:
    st.warning("DATABASE_URL is not set.")
    st.stop()

can_scrape = bool(settings.apify_api_token and settings.apify_post_url_actor_id)

with st.sidebar:
    st.subheader("Validate")
    force_validate = st.checkbox(
        "Force validate (ignore due date)",
        value=True,
        help="Required for corpus backtests and dev runs before the 48h window.",
    )
    if st.button(
        "Re-scrape selected posts",
        type="primary",
        disabled=not can_scrape,
    ):
        selected = st.session_state.get("validation_selected_ids", [])
        if not selected:
            st.warning("Select rows in the comparison table first.")
        else:
            with st.spinner(f"Re-scraping {len(selected)} post(s) by URL..."):
                batch = run_validations_for_ids(
                    [UUID(pid) for pid in selected],
                    settings,
                    ignore_due_date=force_validate,
                )
            st.session_state["last_batch"] = batch

    st.divider()
    st.subheader("Run all due")
    limit = st.number_input("Batch limit", min_value=1, max_value=200, value=50)
    if st.button("Run due validations", disabled=not can_scrape):
        with st.spinner("Processing due validations..."):
            batch = run_due_validations(settings, limit=int(limit))
        st.session_state["last_batch"] = batch

    if not settings.apify_post_url_actor_id:
        st.warning("Set APIFY_POST_URL_ACTOR_ID (default: harvestapi/linkedin-profile-posts)")

if "last_batch" in st.session_state:
    batch = st.session_state["last_batch"]
    render_validation_batch_summary(batch)
    fingerprint = (
        batch.processed,
        batch.validated,
        batch.failed,
        str(batch.results[0].prediction_id) if batch.results else "",
    )
    if st.session_state.get("_last_batch_fingerprint") != fingerprint:
        st.session_state["validation_queue_show"] = "Validated"
        st.session_state["_last_batch_fingerprint"] = fingerprint

# Apply deferred Show-filter changes before the selectbox is created.
if "validation_queue_show_pending" in st.session_state:
    st.session_state["validation_queue_show"] = st.session_state.pop(
        "validation_queue_show_pending"
    )

status_cols = st.columns([2, 1, 1])
with status_cols[0]:
    status_filter = st.selectbox(
        "Show",
        ["All", "Scheduled", "Validated", "Failed"],
        key="validation_queue_show",
    )
with status_cols[1]:
    st.write("")  # vertical align with selectbox
    if st.button("Select all scheduled", use_container_width=True):
        scheduled = load_predictions(settings, status="scheduled", limit=200)
        ids = [str(p.prediction_id) for p in scheduled]
        if not ids:
            st.warning("No scheduled predictions to select.")
        else:
            st.session_state["validation_selected_ids"] = ids
            st.session_state["validation_preselected_ids"] = ids
            st.session_state["validation_comparison_rev"] = (
                st.session_state.get("validation_comparison_rev", 0) + 1
            )
            st.session_state["validation_queue_show_pending"] = "Scheduled"
            st.rerun()
with status_cols[2]:
    st.write("")
    if st.button("Clear selection", use_container_width=True):
        st.session_state["validation_selected_ids"] = []
        st.session_state["validation_preselected_ids"] = []
        st.session_state["validation_comparison_rev"] = (
            st.session_state.get("validation_comparison_rev", 0) + 1
        )
        st.rerun()

status_map = {
    "All": None,
    "Scheduled": "scheduled",
    "Validated": "validated",
    "Failed": "failed",
}
predictions = load_predictions(settings, status=status_map[status_filter], limit=200)
selected_count = len(st.session_state.get("validation_selected_ids", []))
if selected_count:
    st.caption(f"{selected_count} post(s) selected for re-scrape.")
render_validation_comparison_table(
    predictions,
    editor_key=f"validation_comparison_main_{st.session_state.get('validation_comparison_rev', 0)}",
    selectable=True,
    preselected_ids=st.session_state.get("validation_preselected_ids") or None,
)
