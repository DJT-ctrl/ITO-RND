"""Validation Pipeline — queue, comparison view, and selected re-scrapes."""

import asyncio
import sys
from pathlib import Path
from uuid import UUID

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from config.settings import load_settings  # noqa: E402
from validation_pipeline.corpus_import import (  # noqa: E402
    corpus_row_to_collected,
    import_corpus_posts_async,
    list_corpus_artifact_files,
    load_corpus_posts_from_db,
    load_corpus_posts_from_file,
)
from validation_pipeline.ui import (  # noqa: E402
    load_predictions,
    render_validation_comparison_table,
)
from validation_pipeline.worker import run_due_validations, run_validations_for_ids  # noqa: E402

st.set_page_config(page_title="Validation Queue", layout="wide")
st.title("Validation Pipeline — Queue")
st.caption(
    "Compare baseline (T0), predicted, and actual engagement. "
    "Re-scrape uses direct LinkedIn post URLs in one batched Apify call."
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

    st.divider()
    st.subheader("Import from corpus")
    corpus_source = st.radio("Source", ["Database corpus", "Artifact file"], horizontal=True)
    corpus_limit = st.number_input("Max posts", min_value=1, max_value=100, value=20)
    due_immediately = st.checkbox("Due immediately (for testing)", value=True)

    if corpus_source == "Database corpus":
        corpus_search = st.text_input("Search corpus", placeholder="keyword or post id")
        corpus_rows = load_corpus_posts_from_db(
            settings, limit=int(corpus_limit), search=corpus_search
        )
        st.caption(f"{len(corpus_rows)} post(s) available")
        if st.button("Import + predict from DB", disabled=not settings.gemini_api_key):
            posts = [p for row in corpus_rows if (p := corpus_row_to_collected(row))]
            with st.spinner(f"Predicting {len(posts)} corpus post(s)..."):
                result = asyncio.run(
                    import_corpus_posts_async(
                        posts,
                        settings,
                        due_immediately=due_immediately,
                    )
                )
            st.session_state["last_import"] = result
    else:
        artifacts = list_corpus_artifact_files(settings)
        artifact_labels = [p.name for p in artifacts]
        picked = st.selectbox("Artifact file", options=artifact_labels or ["—"], index=0)
        if artifacts and st.button("Import + predict from file", disabled=not settings.gemini_api_key):
            path = artifacts[artifact_labels.index(picked)]
            rows = load_corpus_posts_from_file(path)
            posts = [p for row in rows[: int(corpus_limit)] if (p := corpus_row_to_collected(row))]
            with st.spinner(f"Predicting {len(posts)} post(s) from {path.name}..."):
                result = asyncio.run(
                    import_corpus_posts_async(
                        posts,
                        settings,
                        due_immediately=due_immediately,
                    )
                )
            st.session_state["last_import"] = result

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

if "last_import" in st.session_state:
    imp = st.session_state["last_import"]
    st.info(f"Imported {imp.imported} · Skipped {imp.skipped} · Errors {len(imp.errors)}")
    for err in imp.errors:
        st.error(err)

tab_compare, tab_scheduled, tab_validated, tab_failed = st.tabs(
    ["Compare (all)", "Scheduled", "Validated", "Failed"]
)

with tab_compare:
    render_validation_comparison_table(load_predictions(settings, limit=200))
with tab_scheduled:
    render_validation_comparison_table(load_predictions(settings, status="scheduled", limit=200))
with tab_validated:
    render_validation_comparison_table(load_predictions(settings, status="validated", limit=200))
with tab_failed:
    render_validation_comparison_table(load_predictions(settings, status="failed", limit=200))
