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
    render_how_this_connects,
    render_manual_actions,
    render_recent_feedback_table,
    render_review_queue,
)
from feedback.observability_ui import (  # noqa: E402
    render_cluster_accuracy,
    render_learning_status,
    render_offline_evaluation_panel,
)

st.set_page_config(page_title="Feedback Loop", layout="wide")
st.title("Validation Pipeline — Feedback Loop")
st.caption(
    "Closed-loop learning: calibration offsets, cluster routing, structured "
    "feedback lessons, and prompt injection. Phase F go/no-go from the latest "
    "offline eval is shown under **Learning active?** and again in "
    "**Offline evaluation**. Use the **?** on each section for a plain-English "
    "explanation."
)

settings = load_settings()

if not settings.database_url:
    st.warning("DATABASE_URL is not set.")
    st.stop()

settings = render_feedback_settings_panel(settings)

st.divider()
render_learning_status(settings)

st.divider()
render_offline_evaluation_panel(settings)

st.divider()
render_calibration_panel(settings)

st.divider()
coverage = render_coverage_panel(settings)

st.divider()
render_manual_actions(settings)

st.divider()
render_review_queue(settings)

st.divider()
clusters = render_clusters_table(
    settings, cluster_n_min=settings.validation_cluster_n_min
)

st.divider()
render_cluster_accuracy(settings)

cluster_filter = None
if clusters:
    choices = ["All clusters"] + [c.cluster_id for c in clusters]
    pick = st.selectbox(
        "Filter feedback by cluster",
        choices,
        help=(
            "Show only lessons from one bucket (e.g. short_list_micro). "
            "This is the same routing used at predict time for injection."
        ),
    )
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
render_how_this_connects(settings)

if coverage["validated"] == 0:
    st.info(
        "No validated predictions yet — collect & predict, then validate in the Queue "
        "before feedback and calibration have data to learn from."
    )
