"""Enable / disable agentic jobs (scheduler will honor these in T10.3)."""

from __future__ import annotations

import streamlit as st

from phase_10.job_flags import load_job_flags, save_job_flags
from phase_10.models import JOB_FLAG_KEYS, JOB_FLAG_LABELS


def render_flags_panel() -> None:
    st.subheader("Job flags")
    st.caption(
        "Start/stop switches for background jobs. The scheduler (T10.3) will "
        "skip disabled jobs; flags alone do not run scrapers."
    )

    current = load_job_flags().to_dict()
    drafts: dict[str, bool] = {}
    for key in JOB_FLAG_KEYS:
        drafts[key] = st.toggle(
            JOB_FLAG_LABELS[key],
            value=bool(current[key]),
            key=f"agentic_flag_{key}",
        )

    if st.button("Save job flags", type="primary", key="agentic_save_flags"):
        save_job_flags(drafts)
        st.success("Job flags saved.")
        st.rerun()
