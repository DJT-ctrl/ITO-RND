"""Validation Pipeline — queue, comparison view, and selected re-scrapes."""

import sys
from pathlib import Path
from uuid import UUID

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from config.settings import load_settings  # noqa: E402
from validation_pipeline.ui import (  # noqa: E402
    load_predictions,
    render_validation_comparison_table,
)
from validation_pipeline.worker import run_due_validations, run_validations_for_ids  # noqa: E402

st.set_page_config(page_title="Validation Queue", layout="wide")
st.title("Validation Pipeline — Queue")
st.caption(
    "Compare baseline (T0), predicted, and actual engagement. "
    "Re-scrape uses direct LinkedIn post URLs in one batched Apify call. "
    "After validate, template feedback is stored automatically — manage it on "
    "**Feedback Loop**."
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
    st.success(
        f"Processed {batch.processed} · Validated {batch.validated} · Failed {batch.failed}"
    )
    for item in batch.results:
        if item.status == "failed":
            st.error(f"{item.prediction_id}: {item.error}")
        elif item.status == "skipped" and item.error:
            st.warning(item.error)

status_filter = st.selectbox(
    "Show",
    ["All", "Scheduled", "Validated", "Failed"],
    index=0,
)
status_map = {
    "All": None,
    "Scheduled": "scheduled",
    "Validated": "validated",
    "Failed": "failed",
}
predictions = load_predictions(settings, status=status_map[status_filter], limit=200)
render_validation_comparison_table(
    predictions,
    editor_key="validation_comparison_main",
    selectable=True,
)
