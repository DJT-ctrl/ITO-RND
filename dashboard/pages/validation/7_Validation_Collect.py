"""Validation Pipeline — scrape posts, predict engagement, schedule 48h validation."""

import asyncio
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from config.settings import load_settings  # noqa: E402
from telemetry.apify import load_apify_runs  # noqa: E402
from telemetry.apify_ui import render_apify_cost_history, render_apify_session_cost  # noqa: E402
from validation_pipeline.pipeline import run_collect_and_predict  # noqa: E402
from validation_pipeline.ui import load_predictions, render_predictions_table  # noqa: E402

st.set_page_config(page_title="Validation Collect", layout="wide")
st.title("Validation Pipeline — Collect & Predict")
st.caption(
    "Scrape fresh LinkedIn posts, run the RAG predictor, and schedule re-scrape validation "
    "after the configured window (default 48h)."
)

settings = load_settings()

with st.sidebar:
    st.subheader("Search")
    search_query = st.text_input("Search query", value="ai marketing")
    max_posts = st.number_input(
        "Max posts",
        min_value=1,
        max_value=100,
        value=settings.validation_max_posts_per_run,
    )
    st.caption("Author profiles are always scraped for personal-profile posts.")
    window_hours = settings.validation_window_hours
    if settings.validation_dev_window_minutes is not None:
        st.info(f"Dev validation window: {settings.validation_dev_window_minutes} minutes")
    else:
        st.info(f"Validation window: {window_hours} hours after publish")

    can_run = bool(
        settings.apify_api_token
        and settings.apify_actor_id
        and settings.apify_profile_actor_id
        and settings.gemini_api_key
        and settings.database_url
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

if run_clicked:
    search_params = {
        "searchQueries": [search_query.strip()],
        "maxPosts": int(max_posts),
        "sortBy": "date",
        "postedLimit": "week",
    }
    log = st.empty()
    messages: list[str] = []

    def on_progress(msg: str) -> None:
        messages.append(msg)
        log.code("\n".join(messages[-8:]))

    with st.spinner("Running collect + predict..."):
        result = asyncio.run(
            run_collect_and_predict(
                search_params,
                settings=settings,
                on_progress=on_progress,
            )
        )
    st.session_state["last_collect_result"] = result

if "last_collect_result" in st.session_state:
    result = st.session_state["last_collect_result"]
    st.success(
        f"Scraped {result.scraped} · Predicted {result.predicted} · "
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
