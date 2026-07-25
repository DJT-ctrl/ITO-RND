"""Last / next run status (filled by T10.3)."""

from __future__ import annotations

import streamlit as st

from phase_10.schedule import get_schedule_status


def render_schedule_panel() -> None:
    st.subheader("Schedule")
    status = get_schedule_status()

    if status.stub:
        st.caption(
            "No scheduler yet (T10.3). Rows show enable state from job flags; "
            "last/next remain empty until jobs are wired."
        )

    rows = [
        {
            "Job": job.label,
            "Enabled": "yes" if job.enabled else "no",
            "Last run": job.last_run_at or "—",
            "Next run": job.next_run_at or "—",
            "Status": job.last_result or "—",
        }
        for job in status.jobs
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)
