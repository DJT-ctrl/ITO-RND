"""Validation Pipeline — accuracy history and calibration metrics."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from config.settings import load_settings  # noqa: E402
from validation_pipeline.ui import load_predictions, render_accuracy_summary, render_predictions_table  # noqa: E402

st.set_page_config(page_title="Accuracy History", layout="wide")
st.title("Validation Pipeline — Accuracy History")
st.caption(
    "Percentile and per-metric count accuracy after scheduled re-scrape "
    "(likes, comments, shares)."
)

settings = load_settings()

if not settings.database_url:
    st.warning("DATABASE_URL is not set.")
    st.stop()

render_accuracy_summary(settings, compact=False)

st.divider()
st.subheader("Recent validated predictions")
validated = load_predictions(settings, status="validated", limit=50)
if validated:
    render_predictions_table(validated)
    count_rows = []
    for p in validated:
        if p.likes_delta is None:
            continue
        count_rows.append(
            {
                "post_id": p.linkedin_post_id,
                "likes_Δ": abs(p.likes_delta or 0),
                "comments_Δ": abs(p.comments_delta or 0),
                "shares_Δ": abs(p.shares_delta or 0),
                "total_Δ": abs(p.total_engagement_delta or 0),
            }
        )
    if count_rows:
        st.subheader("Absolute count error by post")
        st.bar_chart(pd.DataFrame(count_rows).set_index("post_id"), height=280)
else:
    st.info("No validated predictions yet.")
