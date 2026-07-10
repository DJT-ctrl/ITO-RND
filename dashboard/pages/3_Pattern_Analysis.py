"""Throwaway visual test harness for Phase B — the pattern-analysis step.

Loads one or more finalized pipeline bundles (Stage 1 + 2 analysed JSONL)
and shows three views, from simplest to most involved:
  - Engagement by tag   — group_engagement_by_tag()
  - Numeric correlation — correlate_numeric_features()
  - Feature importance  — feature_importance() (only if enough rows)

Not the product UI — exists purely to eyeball whether the pipeline's
output actually shows real, sane patterns before building anything on top
of it. Mirrors the structure of dashboard/pages/2_Post_Analyser.py.
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from dashboard.pipeline_ui import load_records_from_bundles, render_bundle_multiselect  # noqa: E402
from processors.pattern_analysis import (  # noqa: E402
    correlate_numeric_features,
    feature_importance,
    group_engagement_by_tag,
)

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Pattern Analysis Test Harness", layout="wide")
st.title("Phase B: Pattern & Correlation Analysis")
st.caption(
    "Throwaway visual tool for the T1.2 follow-on pattern-finding step. "
    "Plain statistics only — no Gemini/LLM involved here on purpose. "
    "Select one or more analysed pipeline bundles from Step 2."
)

# ── Sidebar: pick pipeline bundle(s) ──────────────────────────────────────────

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

# ── Analyses ──────────────────────────────────────────────────────────────────

if records:
    gemini_populated = sum(1 for r in records if r.get("hook_type") is not None)
    if gemini_populated == 0:
        st.warning(
            "No Gemini qualitative tags in this dataset — tag-based views will be empty. "
            "Re-run Step 2 with Stage 1 + 2."
        )

    st.subheader("Engagement by Tag")
    st.caption("Mean/median engagement_zscore grouped by each available categorical tag.")
    tag_groups = group_engagement_by_tag(records)
    if tag_groups:
        for tag, table in tag_groups.items():
            st.markdown(f"**{tag}**")
            st.dataframe(table, use_container_width=True)
    else:
        st.info("No categorical tags present — re-run Step 2 with Stage 1 + 2 (Gemini).")

    st.subheader("Numeric Feature Correlation")
    st.caption("Pearson correlation of each numeric feature against engagement_zscore.")
    try:
        correlations = correlate_numeric_features(records)
        st.dataframe(correlations.rename("correlation"), use_container_width=True)
    except ValueError as exc:
        st.info(str(exc))

    st.subheader("Feature Importance (optional ML)")
    st.caption("Gradient-boosted regressor predicting engagement_zscore. Needs enough rows to be meaningful.")
    try:
        importances = feature_importance(records)
        st.dataframe(importances.rename("importance"), use_container_width=True)
    except ValueError as exc:
        st.info(str(exc))
