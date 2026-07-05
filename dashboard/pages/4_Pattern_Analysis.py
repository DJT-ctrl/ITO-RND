"""Throwaway visual test harness for Phase B — the pattern-analysis step.

Loads a consolidated dataset produced by ``processors/run_pipeline.py``
(a data/processed/*.jsonl file) and shows three views, from simplest to
most involved:
  - Engagement by tag   — group_engagement_by_tag()
  - Numeric correlation — correlate_numeric_features()
  - Feature importance  — feature_importance() (only if enough rows)

Not the product UI — exists purely to eyeball whether the pipeline's
output actually shows real, sane patterns before building anything on top
of it. Mirrors the structure of dashboard/pages/3_Post_Analyser.py.
"""

import json
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

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
    "Plain statistics only — no Gemini/LLM involved here on purpose."
)

# ── Sidebar: pick a processed dataset ─────────────────────────────────────────

with st.sidebar:
    st.header("1. Load a processed dataset")
    processed_dir = Path("data/processed")
    dataset_files = sorted(processed_dir.glob("*.jsonl"), reverse=True) if processed_dir.exists() else []

    records: list[dict] = []
    if dataset_files:
        selected_file = st.selectbox("Saved datasets", ["-- Select --"] + [f.name for f in dataset_files])
        if selected_file != "-- Select --":
            with (processed_dir / selected_file).open(encoding="utf-8") as fh:
                records = [json.loads(line) for line in fh if line.strip()]
            st.info(f"{len(records)} post(s) loaded.")
    else:
        st.warning("No processed datasets found. Run `python -m processors.run_pipeline` first.")

# ── Analyses ──────────────────────────────────────────────────────────────────

if records:
    st.subheader("Engagement by Tag")
    st.caption("Mean/median engagement_zscore grouped by each available categorical tag.")
    tag_groups = group_engagement_by_tag(records)
    if tag_groups:
        for tag, table in tag_groups.items():
            st.markdown(f"**{tag}**")
            st.dataframe(table, use_container_width=True)
    else:
        st.info("No categorical tags present — re-run the pipeline with --with-gemini to get them.")

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
