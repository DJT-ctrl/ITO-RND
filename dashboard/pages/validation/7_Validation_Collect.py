"""Validation Pipeline — collect & predict from live scrape or saved collections.

Phase 11: each post auto-creates a same-age grade (Lane A) plus fixed 24/48/72h
horizon predictions (Lane B) under Gemini budget caps.
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
    count_already_predicted,
    list_saved_collections,
)
from validation_pipeline.pipeline import run_collect_and_predict, run_predict_on_posts  # noqa: E402
from validation_pipeline.reset import reset_validation_data_for_settings  # noqa: E402
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
    "scrape fresh posts, or load a saved collection. Multi-horizon mode writes "
    "same-age + 24/48/72h predictions per post.",
    step_hint="Validation step 1 of 4 · Next: Validation queue · Phase 11",
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

**Phase 11:** each post gets a **same-age** immediate grade plus **24h / 48h / 72h**
scheduled rows (blind predict). Cap: `VALIDATION_MULTI_HORIZON_MAX_PREDICTS_PER_RUN`.
""",
)
st.caption(f"Predictor model: `{pydantic_ai_gemini_model()}`")
if settings.validation_multi_horizon_enabled:
    st.caption(
        f"Multi-horizon ON — max {settings.validation_multi_horizon_max_predicts_per_run} "
        f"Gemini predicts/run · fixed horizons "
        f"{list(settings.validation_fixed_horizons_hours)}"
    )

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
already_predicted = 0
if posts_ready and settings.database_url:
    try:
        already_predicted = count_already_predicted(posts_ready, settings)
    except Exception:
        already_predicted = 0

remaining_to_predict = max(len(posts_ready) - already_predicted, 0)
metric_cols = st.columns(3)
with metric_cols[0]:
    st.metric("Unique vectorized posts", len(posts_ready))
with metric_cols[1]:
    st.metric("Already complete", already_predicted)
with metric_cols[2]:
    st.metric("Remaining to predict", remaining_to_predict)
if already_predicted:
    st.caption(
        "Posts with all planned horizon rows are skipped automatically — "
        "each import run picks the next incomplete posts up to Max posts."
    )

col_reset, col_max = st.columns(2)
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
        value=min(remaining_to_predict or len(posts_ready) or 1, 500),
        key="vectorized_import_max",
    )

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
    and remaining_to_predict
)
st.caption(
    "This step runs **up to four Gemini predictions per post** (same-age + fixed "
    "horizons) under the per-run budget — expect a few seconds each, plus a 1s "
    "pause between posts. Feedback is written later after you grade in "
    "**Validation queue** (Lane A grades immediately)."
)
if st.button(
    "Import vectorized posts and predict",
    type="primary",
    disabled=not can_bulk,
):
    progress = st.progress(0, text="Multi-horizon predict on vectorized corpus...")
    status = st.empty()

    def on_bulk_progress(completed: int, total: int, message: str) -> None:
        fraction = (completed / total) if total else 1.0
        progress.progress(min(max(fraction, 0.0), 1.0), text=message)
        status.caption(message)

    result = bulk_import_vectorized_and_predict(
        settings,
        max_posts=int(bulk_max),
        on_progress=on_bulk_progress,
    )
    progress.progress(
        1.0,
        text=(
            f"Done — imported={result.imported} skipped={result.skipped} "
            f"errors={len(result.errors)}"
        ),
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
    if settings.validation_multi_horizon_enabled:
        st.info(
            "Multi-horizon: same-age grade now + 24/48/72h rescrape rows "
            f"(budget ≤ {settings.validation_multi_horizon_max_predicts_per_run}/run)."
        )
    elif settings.validation_dev_window_minutes is not None:
        st.info(f"Dev validation window: {settings.validation_dev_window_minutes} minutes")
    else:
        st.info(f"Legacy window: {settings.validation_window_hours}h after publish")

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

    with st.spinner("Running multi-horizon collect/predict..."):
        if source_mode == "Live Apify scrape":
            search_params = {
                "searchQueries": [search_query.strip()],
                "maxPosts": int(max_posts),
                "sortBy": "relevance",
            }
            result = asyncio.run(
                run_collect_and_predict(
                    search_params,
                    settings=settings,
                    on_progress=on_progress,
                )
            )
            st.session_state["last_apify_runs"] = load_apify_runs(limit=20)
        else:
            from config.paths import resolve_data_path

            path = resolve_data_path(settings.raw_data_dir) / selected_scan
            posts = collected_posts_from_saved_collection(
                path, settings, max_posts=int(max_posts)
            )
            result = asyncio.run(
                run_predict_on_posts(
                    posts,
                    settings=settings,
                    on_progress=on_progress,
                )
            )

    st.session_state["validation_last_result"] = result
    st.rerun()

if "validation_last_result" in st.session_state:
    last = st.session_state["validation_last_result"]
    st.success(
        f"scraped/loaded={last.scraped} predicted={last.predicted} "
        f"skipped={last.skipped} budget_skipped={getattr(last, 'budget_skipped', 0)} "
        f"errors={len(last.errors)}"
    )
    if last.errors:
        for err in last.errors[:10]:
            st.error(err)
    if last.predictions:
        render_predictions_table(last.predictions)

st.divider()
render_apify_session_cost()
render_apify_cost_history()
