"""Streamlit panels for the Agentic Layer tab."""

from __future__ import annotations

import streamlit as st

from phase_10.ui.budget_panel import render_budget_panel
from phase_10.ui.digests_panel import render_digests_panel
from phase_10.ui.flags_panel import render_flags_panel
from phase_10.ui.plan_panel import render_plan_panel
from phase_10.ui.schedule_panel import render_schedule_panel
from phase_10.ui.seeds_panel import render_seeds_panel


def render_agentic_layer() -> None:
    """Compose the Agentic Layer page (ops UI only)."""
    render_seeds_panel()
    st.divider()
    render_plan_panel()
    st.divider()
    render_flags_panel()
    st.divider()
    render_schedule_panel()
    st.divider()
    render_budget_panel()
    st.divider()
    render_digests_panel()
