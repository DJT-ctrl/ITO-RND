"""Validation Pipeline — accuracy history and calibration metrics."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from config.settings import load_settings  # noqa: E402
from validation_pipeline.ui import load_predictions, render_accuracy_summary  # noqa: E402

st.set_page_config(page_title="Accuracy History", layout="wide")
st.title("Validation Pipeline — Accuracy History")
st.caption("How closely predicted engagement percentiles match actual outcomes after re-scrape.")

settings = load_settings()

if not settings.database_url:
    st.warning("DATABASE_URL is not set.")
    st.stop()

render_accuracy_summary(settings, compact=False)

st.divider()
st.subheader("Recent validated predictions")
validated = load_predictions(settings, status="validated", limit=50)
if validated:
    rows = []
    for p in validated:
        rows.append(
            {
                "post_id": p.linkedin_post_id,
                "predicted": p.predicted_engagement_percentile,
                "actual": p.actual_engagement_percentile,
                "delta": p.prediction_delta,
                "accuracy": p.accuracy_score,
                "validated_at": p.validated_at,
            }
        )
    df = pd.DataFrame(rows)
    if "accuracy" in df.columns and not df["accuracy"].dropna().empty:
        st.bar_chart(df.set_index("post_id")[["accuracy"]], height=280)
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("No validated predictions yet.")
