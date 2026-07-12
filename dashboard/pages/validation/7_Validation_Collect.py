"""Validation Pipeline — collect & predict from live scrape or saved collections."""

import asyncio
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from config.paths import resolve_data_path  # noqa: E402
from config.settings import load_settings  # noqa: E402
from telemetry.apify import load_apify_runs  # noqa: E402
from telemetry.apify_ui import render_apify_cost_history, render_apify_session_cost  # noqa: E402
from validation_pipeline.corpus_import import (  # noqa: E402
    collected_posts_from_saved_collection,
    list_saved_collections,
)
from validation_pipeline.pipeline import run_collect_and_predict, run_predict_on_posts  # noqa: E402
from validation_pipeline.ui import load_predictions, render_predictions_table  # noqa: E402

st.set_page_config(page_title="Validation Collect", layout="wide")
st.title("Validation Pipeline — Collect & Predict")
st.caption(
    "Scrape fresh posts or reuse a Scraper Stage collection, run the predictor, "
    "and schedule validation (default 48h). Calibration + feedback injection "
    "apply at predict time when enabled — see **Feedback Loop**."
)

settings = load_settings()

with st.sidebar:
    source_mode = st.radio(
        "Source",
        ["Live Apify scrape", "Saved collection (Scraper Stage)"],
        help="Saved collections are the linkedin_*.json files from Scraper Stage.",
    )

    st.subheader("Predict")
    max_posts = st.number_input(
        "Max posts",
        min_value=1,
        max_value=100,
        value=settings.validation_max_posts_per_run,
    )
    due_immediately = st.checkbox(
        "Due immediately (for testing)",
        value=False,
        help="Skip the 48h wait — use with saved collections to test validation in Queue.",
    )

    window_hours = settings.validation_window_hours
    if settings.validation_dev_window_minutes is not None:
        st.info(f"Dev validation window: {settings.validation_dev_window_minutes} minutes")
    elif due_immediately:
        st.info("Predictions will be due for validation immediately.")
    else:
        st.info(f"Validation window: {window_hours} hours after publish")

    can_predict = bool(settings.gemini_api_key and settings.database_url)

    if source_mode == "Live Apify scrape":
        search_query = st.text_input("Search query", value="ai marketing")
        can_run = can_predict and bool(
            settings.apify_api_token
            and settings.apify_actor_id
            and settings.apify_profile_actor_id
        )
        if not can_run:
            missing = []
            if not settings.apify_api_token:
                missing.append("APIFY_API_TOKEN")
            if not settings.apify_actor_id:
                missing.append("APIFY_ACTOR_ID")
            if not settings.apify_profile_actor_id:
                missing.append("APIFY_PROFILE_ACTOR_ID")
            if not settings.gemini_api_key:
                missing.append("GEMINI_API_KEY")
            if not settings.database_url:
                missing.append("DATABASE_URL")
            st.warning(f"Missing: {', '.join(missing)}")
        run_clicked = st.button("Run Collect + Predict", type="primary", disabled=not can_run)
    else:
        saved_scans = list_saved_collections(settings)
        if saved_scans:
            scan_options = ["-- Select a saved collection --"] + [f.name for f in saved_scans]
            selected_scan = st.selectbox(
                "Saved collections",
                scan_options,
                help="Same files as Scraper Stage → Load Previous Collection.",
            )
        else:
            selected_scan = "-- Select a saved collection --"
            st.info(f"No saved collections in `{resolve_data_path(settings.raw_data_dir)}`.")

        can_run = (
            can_predict
            and selected_scan != "-- Select a saved collection --"
        )
        run_clicked = st.button("Run Predict on Collection", type="primary", disabled=not can_run)

if run_clicked:
    log = st.empty()
    messages: list[str] = []

    def on_progress(msg: str) -> None:
        messages.append(msg)
        log.code("\n".join(messages[-8:]))

    with st.spinner("Running..."):
        if source_mode == "Live Apify scrape":
            search_params = {
                "searchQueries": [search_query.strip()],
                "maxPosts": int(max_posts),
                "sortBy": "date",
                "postedLimit": "week",
            }
            result = asyncio.run(
                run_collect_and_predict(
                    search_params,
                    settings=settings,
                    on_progress=on_progress,
                )
            )
        else:
            scan_path = next(f for f in saved_scans if f.name == selected_scan)
            posts = collected_posts_from_saved_collection(
                scan_path,
                settings,
                max_posts=int(max_posts),
            )
            on_progress(f"Loaded {len(posts)} post(s) from `{selected_scan}`.")
            result = asyncio.run(
                run_predict_on_posts(
                    posts,
                    settings=settings,
                    due_immediately=due_immediately,
                    on_progress=on_progress,
                )
            )
    st.session_state["last_collect_result"] = result

if "last_collect_result" in st.session_state:
    result = st.session_state["last_collect_result"]
    st.success(
        f"Posts {result.scraped} · Predicted {result.predicted} · "
        f"Skipped {result.skipped} · Errors {len(result.errors)}"
    )
    validation_runs = [
        r
        for r in load_apify_runs(settings, limit=30)
        if r.context and r.context.startswith("validation")
    ][:5]
    if validation_runs:
        render_apify_session_cost(validation_runs)
    if result.errors:
        for err in result.errors:
            st.error(err)
    if result.predictions:
        st.subheader("Newly scheduled predictions")
        render_predictions_table(result.predictions)

st.divider()
render_apify_cost_history(settings, limit=40)
st.divider()
st.subheader("Recent predictions")
if settings.database_url:
    recent = load_predictions(settings, limit=20)
    render_predictions_table(recent)
else:
    st.warning("DATABASE_URL required to list predictions.")
