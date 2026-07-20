"""Check and learn — Feedback loop (calibration, lessons, clusters, gates)."""

import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from config.settings import load_settings  # noqa: E402
from dashboard.chrome import (  # noqa: E402
    page_header,
    pipeline_flow_strip,
    render_how_phases_connect,
    render_phase_legend,
    section_header,
)
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

st.set_page_config(page_title="Feedback loop", layout="wide")
page_header(
    "Feedback loop",
    "After we grade predictions, this page is where the system can **learn**: "
    "save lessons, sort them into buckets, optionally nudge scores, and "
    "optionally show lessons to the predictor. Most learning switches stay "
    "**OFF** until Phase F says the offline test improved enough.",
    step_hint="Validation step 4 of 4 · Use the ? on each section for plain English",
)
pipeline_flow_strip("validation", "feedback")

section_header(
    "What is this page?",
    """
Think of three learning mechanisms:

1. **Save lessons** after grading (Phase B) — usually ON.
2. **Nudge the number** using past errors (Phase A calibration) — OFF until F is GO.
3. **Show lesson text** to the predictor (Phase D injection) — OFF until F is GO.

Everything else on this page supports those: buckets (C), measurement (E/F),
smarter lessons (G), meaning-based routing (H), job queue (I), shadow mode (J).
""",
)
render_how_phases_connect()

with st.expander("Full phase color legend (A–J)", expanded=False):
    render_phase_legend()

settings = load_settings()

if not settings.database_url:
    st.warning("DATABASE_URL is not set.")
    st.stop()

section_header(
    "1 · Learning switches",
    """
These toggles are the main controls. Safe production default: **lessons ON**,
**calibration OFF**, **prompt injection OFF**. Overrides are saved and apply
on the next settings reload (this page, workers, CLI).
""",
)
settings = render_feedback_settings_panel(settings)

st.divider()
section_header(
    "2 · Are we allowed to turn learning on?",
    """
**Learning active?** summarises whether calibration / injection should be live.
**Offline evaluation (Phase F)** is the formal go/no-go test — need enough
average-error improvement before flipping switches.
""",
)
render_learning_status(settings)
st.divider()
render_offline_evaluation_panel(settings)

st.divider()
section_header(
    "3 · Day-to-day work",
    """
After you validate posts in the **Validation queue**, drain the feedback job
queue here, refresh cluster stats, and review LLM lessons (approve/reject)
before they can be injected.
""",
)
render_manual_actions(settings)
st.divider()
render_review_queue(settings)

st.divider()
section_header(
    "4 · Deeper detail",
    """
Calibration, coverage, clusters, and raw lesson tables. Each inner section
still has its own **?** help button.
""",
)

with st.expander("Calibration offsets (Phase A)", expanded=False):
    render_calibration_panel(settings)

st.divider()
coverage = render_coverage_panel(settings)

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
        "No graded predictions yet — use **Collect and predict**, then "
        "**Validation queue**, before feedback and calibration have data to learn from."
    )
