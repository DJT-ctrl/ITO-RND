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
    render_feedback_detail_expander,
    render_feedback_settings_panel,
    render_manual_actions,
    render_recent_feedback_table,
    render_review_queue,
)
from feedback.understand_ui import render_understand_learning_tab  # noqa: E402
from feedback.observability_ui import (  # noqa: E402
    render_learning_status,
    render_offline_evaluation_panel,
)

st.set_page_config(page_title="Feedback loop", layout="wide")
page_header(
    "Feedback loop",
    "After we grade predictions, this page is where the system can **learn**. "
    "Use **Operate** for switches and jobs. Use **Understand learning** for "
    "how feedback works, full written lessons, and bucket / B·G explorers.",
    step_hint="Validation step 4 of 4 · Two tabs: Operate · Understand learning",
)
pipeline_flow_strip("validation", "feedback")

settings = load_settings()

if not settings.database_url:
    st.warning("DATABASE_URL is not set.")
    st.stop()

operate_tab, understand_tab = st.tabs(
    ["Operate", "Understand learning"]
)

with operate_tab:
    section_header(
        "What is this tab?",
        """
Controls and day-to-day work:

1. **Save lessons** after grading (Phase B) — usually ON.
2. **Nudge the number** using past errors (Phase A) — OFF until F is GO.
3. **Show lesson text** to the predictor (Phase D) — OFF until F is GO.

For “how does learning work?” and bucket / full-lesson explorers, open
**Understand learning**.
""",
    )
    render_how_phases_connect()

    with st.expander("Full phase color legend (A–J)", expanded=True):
        render_phase_legend()

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
        "4 · Coverage & calibration",
        """
How many graded posts have lessons, and what the global calibration offset is.
Bucket explorers and full lesson write-ups live on **Understand learning**.
""",
    )
    with st.expander("Calibration offsets (Phase A)", expanded=False):
        render_calibration_panel(settings)

    st.divider()
    coverage = render_coverage_panel(settings)

    st.divider()
    records = render_recent_feedback_table(settings, limit=30)
    if records:
        st.divider()
        render_feedback_detail_expander(records)

    if coverage["validated"] == 0:
        st.info(
            "No graded predictions yet — use **Collect and predict**, then "
            "**Validation queue**, before feedback and calibration have data "
            "to learn from."
        )

with understand_tab:
    # Reload settings so Understand reflects any Operate-tab toggles after save+rerun.
    settings = load_settings()
    render_understand_learning_tab(settings)
