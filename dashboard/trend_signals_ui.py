"""Draft evaluator helpers for visible Google Trends suggestions.

Keeps Streamlit rendering out of processors/trend_signals and avoids bloating
dashboard/pages/6_Evaluation_Cycle.py.
"""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st

from processors.trend_signals.google_trends import TRENDS_DISCLAIMER


def trend_signal_rows(trends: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize a trends payload into table rows for the Draft evaluator panel."""
    if not trends or not trends.get("signals"):
        return []

    rows: list[dict[str, Any]] = []
    for signal in trends["signals"]:
        recent = signal.get("recent_avg")
        prior = signal.get("prior_avg")
        suggestion = _suggestion_for_direction(str(signal.get("direction") or "unknown"))
        rows.append(
            {
                "keyword": signal.get("keyword") or "—",
                "direction": signal.get("direction") or "unknown",
                "recent_avg": None if recent is None else round(float(recent), 1),
                "prior_avg": None if prior is None else round(float(prior), 1),
                "corpus_alignment": signal.get("corpus_alignment") or "unknown",
                "suggestion": suggestion,
            }
        )
    return rows


def _suggestion_for_direction(direction: str) -> str:
    if direction == "rising":
        return "Timely — consider leaning into this theme while interest is up."
    if direction == "falling":
        return "Cooling — use carefully; may need a fresher angle."
    if direction == "flat":
        return "Stable search interest — weak timing signal either way."
    if direction == "insufficient_data":
        return "Not enough Google Trends history for a clear read."
    return "No clear direction from Google Trends."


def render_trend_signals_panel(
    discoverability_context: Optional[dict[str, Any]],
    *,
    trends_requested: bool,
    extra_warnings: Optional[list[str]] = None,
) -> None:
    """Render the post-evaluate Trend signals section (Google web search, not LinkedIn)."""
    st.subheader("Trend signals (Google — web search, not LinkedIn)")
    st.caption(TRENDS_DISCLAIMER)

    if not trends_requested:
        st.info(
            "Google Trends was off for this run. Enable **Include Google Trends** "
            "in the sidebar and evaluate again to see keyword momentum suggestions."
        )
        return

    context = discoverability_context or {}
    trends = context.get("trends")
    keywords = (trends or {}).get("keywords") or []
    rows = trend_signal_rows(trends if isinstance(trends, dict) else None)

    warnings = list(context.get("warnings") or [])
    if extra_warnings:
        warnings.extend(extra_warnings)
    trend_warnings = [
        w for w in warnings if isinstance(w, str) and "trend" in w.lower()
    ]

    if keywords:
        st.markdown("**Keywords searched:** " + ", ".join(f"`{k}`" for k in keywords))

    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
        for row in rows:
            st.markdown(f"- **{row['keyword']}** ({row['direction']}): {row['suggestion']}")
    else:
        st.warning(
            "No Google Trends signals returned for this draft’s keywords. "
            "pytrends may have failed, rate-limited, or found no interest data."
        )

    if trend_warnings:
        with st.expander(f"{len(trend_warnings)} trend warning(s)", expanded=False):
            for warning in trend_warnings:
                st.caption(warning)
