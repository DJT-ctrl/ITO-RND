"""Corpus step 3 — pattern and correlation views on analysed bundles."""

import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from dashboard.chrome import page_header, pipeline_flow_strip, section_header  # noqa: E402
from dashboard.pipeline_readiness import compute_corpus_readiness  # noqa: E402
from dashboard.pipeline_ui import load_records_from_bundles, render_bundle_multiselect  # noqa: E402
from processors.pattern_analysis import (  # noqa: E402
    correlate_numeric_features,
    feature_importance,
    group_engagement_by_tag,
)

st.set_page_config(page_title="Find patterns", layout="wide")
_corpus_ready = compute_corpus_readiness("patterns")
page_header(
    "Find patterns",
    "Plain statistics on analysed posts — engagement by tag, correlations, "
    "and optional feature importance. **No Gemini calls on this page.**",
    step_hint="Corpus step 3 of 5 · Previous: Analyse posts · Next: Make embeddings",
)
pipeline_flow_strip("corpus", "patterns", readiness=_corpus_ready)

section_header(
    "What you need first",
    """
Load one or more **analysed** pipeline bundles from **Analyse posts** that
completed Stage 2 (Gemini tags). Without those tags, the “engagement by tag”
view will be empty.
""",
)

with st.sidebar:
    st.header("1. Load analysed bundle(s)")
    selected_bundles = render_bundle_multiselect(
        label="Pipeline bundles (Stage 1 + 2)",
        min_stage="analysed",
        key="pattern_bundles",
        require_gemini=True,
        help="Only bundles that completed Gemini analysis are listed.",
    )

records: list[dict] = []
if selected_bundles:
    try:
        records, _ = load_records_from_bundles(selected_bundles)
        st.info(f"{len(records)} post(s) loaded from {len(selected_bundles)} bundle(s).")
        for bundle in selected_bundles:
            st.caption(f"`{bundle.bundle_id}` ← {', '.join(bundle.source_scans)}")
    except ValueError as exc:
        st.error(str(exc))

if records:
    gemini_populated = sum(1 for r in records if r.get("hook_type") is not None)
    if gemini_populated == 0:
        st.warning(
            "No Gemini qualitative tags in this dataset — tag-based views will be empty. "
            "Re-run **Analyse posts** with Stage 1 + 2."
        )

    section_header(
        "Engagement by tag",
        "Mean/median engagement score grouped by each categorical tag "
        "(hook type, etc.). Good sanity check that Stage 2 tags look real.",
    )
    tag_groups = group_engagement_by_tag(records)
    if tag_groups:
        for tag, table in tag_groups.items():
            st.markdown(f"**{tag}**")
            st.dataframe(table, use_container_width=True)
    else:
        st.info("No categorical tags present — re-run Analyse posts with Stage 1 + 2.")

    section_header(
        "Numeric feature correlation",
        "Pearson correlation of each numeric feature against engagement_zscore. "
        "Closer to ±1 means a stronger linear relationship.",
    )
    try:
        correlations = correlate_numeric_features(records)
        st.dataframe(correlations.rename("correlation"), use_container_width=True)
    except ValueError as exc:
        st.info(str(exc))

    section_header(
        "Feature importance (optional ML)",
        "Gradient-boosted model predicting engagement_zscore. Needs enough "
        "rows to be meaningful — treat as exploratory, not production truth.",
    )
    try:
        importances = feature_importance(records)
        st.dataframe(importances.rename("importance"), use_container_width=True)
    except ValueError as exc:
        st.info(str(exc))
