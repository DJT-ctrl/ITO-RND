"""Validation Pipeline — feedback loop: calibration, clusters, lessons, manual runs."""

import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from config.settings import load_settings  # noqa: E402
from feedback.ui import (  # noqa: E402
    render_calibration_panel,
    render_coverage_panel,
    render_clusters_table,
    render_feedback_detail_expander,
    render_feedback_settings_panel,
    render_manual_actions,
    render_recent_feedback_table,
)

st.set_page_config(page_title="Feedback Loop", layout="wide")
st.title("Validation Pipeline — Feedback Loop")
st.caption(
    "Closed-loop learning: calibration offsets, cluster routing, structured "
    "feedback lessons, and prompt injection. Run steps manually when you want."
)

settings = load_settings()

if not settings.database_url:
    st.warning("DATABASE_URL is not set.")
    st.stop()

render_feedback_settings_panel(settings)

st.divider()
render_calibration_panel(settings)

st.divider()
coverage = render_coverage_panel(settings)

st.divider()
render_manual_actions(settings)

st.divider()
clusters = render_clusters_table(
    settings, cluster_n_min=settings.validation_cluster_n_min
)

cluster_filter = None
if clusters:
    choices = ["All clusters"] + [c.cluster_id for c in clusters]
    pick = st.selectbox("Filter feedback by cluster", choices)
    if pick != "All clusters":
        cluster_filter = pick

st.divider()
records = render_recent_feedback_table(
    settings, limit=50, cluster_id=cluster_filter
)

if records:
    st.divider()
    render_feedback_detail_expander(records)

st.divider()
st.markdown(
    """
**How this connects**

1. **Validate** a prediction (Queue) → template feedback is stored automatically  
2. **Calibration** adjusts the next neighbor percentile when N ≥ N_min  
3. **Clusters** route posts by length × format × followers  
4. **Injection** adds recent cluster lessons into the Predictor prompt  

Missing rows? Use **Generate missing feedback** above.  
Need fresh cluster mean_delta? Use **Refresh cluster stats**.
"""
)

if coverage["validated"] == 0:
    st.info(
        "No validated predictions yet — collect & predict, then validate in the Queue "
        "before feedback and calibration have data to learn from."
    )
