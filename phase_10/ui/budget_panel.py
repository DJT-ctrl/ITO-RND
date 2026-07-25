"""Budget used vs placeholder caps (T10.9 ledger later)."""

from __future__ import annotations

import streamlit as st

from config.settings import load_settings
from phase_10.budget import get_budget_snapshot


def _pct(used: float, cap: float) -> float:
    if cap <= 0:
        return 0.0
    return min(100.0, round(100.0 * used / cap, 1))


def render_budget_panel() -> None:
    st.subheader("Budget")
    settings = load_settings()
    snap = get_budget_snapshot(settings)

    a1, a2, g1, g2 = st.columns(4)
    a1.metric("Apify used (USD)", f"{snap.apify_used_usd:.4f}")
    a2.metric(
        "Apify cap (USD)",
        f"{snap.apify_cap_usd:.2f}",
        delta=f"{_pct(snap.apify_used_usd, snap.apify_cap_usd)}% used",
        delta_color="off",
    )
    g1.metric("Gemini used (USD)", f"{snap.gemini_used_usd:.4f}")
    g2.metric(
        "Gemini cap (USD)",
        f"{snap.gemini_cap_usd:.2f}",
        delta=f"{_pct(snap.gemini_used_usd, snap.gemini_cap_usd)}% used",
        delta_color="off",
    )

    if snap.stub_caps and snap.note:
        st.caption(snap.note)

    with st.expander("Raw spend history (existing telemetry)", expanded=False):
        try:
            from telemetry.apify_ui import render_apify_cost_history
            from telemetry.ui import render_gemini_cost_history

            render_apify_cost_history(settings)
            st.divider()
            render_gemini_cost_history(settings)
        except Exception as exc:
            st.warning(f"Telemetry history unavailable: {exc}")
