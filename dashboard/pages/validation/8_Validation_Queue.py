"""Validation Pipeline — queue of scheduled, due, and completed validations."""

import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from config.settings import load_settings  # noqa: E402
from validation_pipeline.ui import load_predictions, render_predictions_table  # noqa: E402
from validation_pipeline.worker import run_due_validations  # noqa: E402

st.set_page_config(page_title="Validation Queue", layout="wide")
st.title("Validation Pipeline — Queue")
st.caption("Track scheduled validations and manually process due re-scrapes.")

settings = load_settings()

with st.sidebar:
    st.subheader("Worker")
    limit = st.number_input("Batch limit", min_value=1, max_value=200, value=50)
    can_run = bool(settings.database_url and settings.apify_api_token)
    if not can_run:
        st.warning("Requires DATABASE_URL and APIFY_API_TOKEN")
    if st.button("Run due validations now", type="primary", disabled=not can_run):
        with st.spinner("Processing due validations..."):
            batch = run_due_validations(settings, limit=int(limit))
        st.session_state["last_batch"] = batch

if "last_batch" in st.session_state:
    batch = st.session_state["last_batch"]
    st.success(
        f"Processed {batch.processed} · Validated {batch.validated} · Failed {batch.failed}"
    )
    for item in batch.results:
        if item.status == "failed":
            st.error(f"{item.prediction_id}: {item.error}")

if not settings.database_url:
    st.warning("DATABASE_URL is not set.")
    st.stop()

tab_scheduled, tab_validated, tab_failed, tab_all = st.tabs(
    ["Scheduled", "Validated", "Failed", "All"]
)

with tab_scheduled:
    render_predictions_table(load_predictions(settings, status="scheduled"))
with tab_validated:
    render_predictions_table(load_predictions(settings, status="validated"))
with tab_failed:
    render_predictions_table(load_predictions(settings, status="failed"))
with tab_all:
    render_predictions_table(load_predictions(settings, limit=100))
