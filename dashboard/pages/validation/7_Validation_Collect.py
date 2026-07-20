"""Validation Pipeline — collect & predict from live scrape or saved collections.

Backtest mode strips engagement metrics from already-aged posts so the predictor
runs blind, then allows immediate validation against real actuals (no 48h wait).
"""

import asyncio
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from config.settings import load_settings, pydantic_ai_gemini_model  # noqa: E402
from dashboard.chrome import (  # noqa: E402
    page_header,
    pipeline_flow_strip,
    render_phase_badges,
    section_header,
)
from telemetry.apify import load_apify_runs  # noqa: E402
from telemetry.apify_ui import render_apify_cost_history, render_apify_session_cost  # noqa: E402
from validation_pipeline.corpus_import import (  # noqa: E402
    collected_posts_from_saved_collection,
    list_saved_collections,
)
from validation_pipeline.pipeline import run_collect_and_predict, run_predict_on_posts  # noqa: E402
from validation_pipeline.reset import reset_validation_data_for_settings  # noqa: E402
from validation_pipeline.schemas import strip_engagement_for_backtest  # noqa: E402
from validation_pipeline.ui import load_predictions, render_predictions_table  # noqa: E402
from validation_pipeline.vectorized_corpus import (  # noqa: E402
    bulk_import_vectorized_and_predict,
    discover_vectorized_datasets,
    load_all_vectorized_collected_posts,
)

st.set_page_config(page_title="Collect and predict", layout="wide")
page_header(
    "Collect and predict",
    "Create predictions to grade later: import an already-vectorized corpus, "
    "scrape fresh posts, or load a saved collection. Each run writes predicted "
    "engagement and schedules a validation check.",
    step_hint="Validation step 1 of 4 · Next: Validation queue",
)
pipeline_flow_strip("validation", "predict")
render_phase_badges(["0"])

settings = load_settings()

# ── Step 1: reset + vectorized corpus import ─────────────────────────────────

section_header(
    "1. Reset and import vectorized corpus",
    """
Use analysed LinkedIn **CSV/JSONL bundles that already have matching `.npy`
embeddings** from **Make embeddings** (not raw scraper JSON). Posts are merged
and deduped by `post_id`, then predicted with the flash-lite model.

**Backtest tip:** aged posts can be predicted “blind” and graded immediately
in the queue (no 48h wait).
""",
)
st.caption(f"Predictor model: `{pydantic_ai_gemini_model()}`")

vectorized_datasets = discover_vectorized_datasets(settings)
if vectorized_datasets:
    for dataset in vectorized_datasets:
        st.markdown(f"- `{dataset.label}`")
else:
    st.warning(
        "No vectorized LinkedIn datasets found. Complete **Analyse posts** then "
        "**Make embeddings** under Build the corpus first."
    )

posts_ready, _ = (
    load_all_vectorized_collected_posts(settings)
    if vectorized_datasets
    else ([], [])
)
st.metric("Unique vectorized posts ready", len(posts_ready))

col_reset, col_max, col_due, col_bt = st.columns(4)
with col_reset:
    if st.button(
        "Reset validation data",
        help="Clear predictions, snapshots, feedback rows, and cluster stats.",
    ):
        reset = reset_validation_data_for_settings(settings)
        st.session_state["validation_reset_counts"] = reset
        st.rerun()
with col_max:
    bulk_max = st.number_input(
        "Max posts",
        min_value=1,
        max_value=2000,
        value=min(len(posts_ready) or 1, 500),
        key="vectorized_import_max",
    )
with col_due:
    bulk_due_now = st.checkbox(
        "Due immediately",
        value=False,
        key="vectorized_due_immediately",
        help="Otherwise validation is scheduled for posted_at + 48h (old posts are already due).",
    )
with col_bt:
    bulk_backtest = st.checkbox(
        "⚡ Backtest mode",
        value=False,
        key="vectorized_backtest",
        help=(
            "Strip likes/comments/shares so the predictor runs blind, "
            "then validate immediately against real actuals. "
            "Use with already-aged posts to skip the 48h wait."
        ),
    )
    if bulk_backtest:
        bulk_due_now = True

if "validation_reset_counts" in st.session_state:
    reset = st.session_state["validation_reset_counts"]
    st.success(
        f"Reset complete — predictions={reset.predictions}, "
        f"feedback={reset.prediction_feedback}, clusters={reset.prediction_clusters}"
    )

can_bulk = bool(
    settings.database_url
    and settings.gemini_api_key
    and vectorized_datasets
    and posts_ready
)
if st.button(
    "Import vectorized posts and predict",
    type="primary",
    disabled=not can_bulk,
):
    with st.spinner(
        "Backtest: predicting blind (engagement stripped)..."
        if bulk_backtest
        else "Predicting vectorized corpus..."
    ):
        result = bulk_import_vectorized_and_predict(
            settings,
            max_posts=int(bulk_max),
            due_immediately=bulk_due_now,
            backtest=bulk_backtest,
        )
    st.session_state["vectorized_import_result"] = result
    st.rerun()

if "vectorized_import_result" in st.session_state:
    bulk = st.session_state["vectorized_import_result"]
    st.success(
        f"Vectorized import: loaded={bulk.loaded} imported={bulk.imported} "
        f"skipped={bulk.skipped} errors={len(bulk.errors)}"
    )
    if bulk.errors:
        for err in bulk.errors[:10]:
            st.error(err)

st.divider()

# ── Step 2: single-run collect / predict ─────────────────────────────────────

st.subheader("2. Single run (live scrape or one saved collection)")

with st.sidebar:
    source_mode = st.radio(
        "Source",
        ["Live Apify scrape", "Saved collection (Collect samples)"],
        help="Saved collections are the linkedin_*.json files from Collect samples.",
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
    backtest_mode = st.checkbox(
        "⚡ Backtest mode",
        value=False,
        help=(
            "Strip engagement metrics so the predictor runs blind on "
            "already-aged posts. Forces 'Due immediately' ON."
        ),
    )
    if backtest_mode:
        due_immediately = True

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
                help="Same files as Collect samples → Load Previous Collection.",
            )
        else:
            selected_scan = "-- Select a saved collection --"
            from config.paths import resolve_data_path

            st.info(f"No saved collections in `{resolve_data_path(settings.raw_data_dir)}`.")

        can_run = can_predict and selected_scan != "-- Select a saved collection --"
        run_clicked = st.button("Run Predict on Collection", type="primary", disabled=not can_run)

if run_clicked:
    log = st.empty()
    messages: list[str] = []

    def on_progress(msg: str) -> None:
        messages.append(msg)
        log.code("\n".join(messages[-8:]))

    with st.spinner(
        "Backtest: predicting blind (engagement stripped)..."
        if backtest_mode
        else "Running..."
    ):
        if source_mode == "Live Apify scrape":
            from validation_pipeline.collect import collect_posts as _collect_posts

            # Match Scraper Stage defaults: relevance, no time filter.
            # date + week triggers LinkedIn's anonymous chronological-search throttle.
            search_params = {
                "searchQueries": [search_query.strip()],
                "maxPosts": int(max_posts),
                "sortBy": "relevance",
            }
            if backtest_mode:
                # Collect first, strip engagement, then predict separately.
                posts = _collect_posts(
                    search_params,
                    settings=settings,
                    on_progress=on_progress,
                )
                posts = strip_engagement_for_backtest(posts)
                on_progress(
                    f"⚡ Backtest: stripped engagement from {len(posts)} post(s)."
                )
                result = asyncio.run(
                    run_predict_on_posts(
                        posts,
                        settings=settings,
                        due_immediately=True,
                        on_progress=on_progress,
                    )
                )
            else:
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
            if backtest_mode:
                posts = strip_engagement_for_backtest(posts)
                on_progress(
                    f"⚡ Backtest: stripped engagement from {len(posts)} post(s) "
                    f"loaded from `{selected_scan}`."
                )
            else:
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
