"""Streamlit UI for Apify scraper cost telemetry."""

from __future__ import annotations

from typing import Optional

import streamlit as st

from config.settings import Settings
from telemetry.apify import load_apify_runs, summarize_apify_runs
from telemetry.apify_schemas import ApifyCostSummary, ApifyRunRecord


def _format_cost(usd: float) -> str:
    if usd < 0.01:
        return f"${usd:.4f}"
    return f"${usd:.3f}"


def render_apify_session_cost(runs: list[ApifyRunRecord]) -> None:
    """Show Apify cost for the current page run."""
    if not runs:
        return
    summary = summarize_apify_runs(runs)
    st.subheader("Apify Scraper Cost")
    c1, c2, c3 = st.columns(3)
    c1.metric("This run — total", _format_cost(summary.total_cost_usd))
    c2.metric("Post search", _format_cost(summary.post_search_cost_usd))
    c3.metric("Profile scrape", _format_cost(summary.profile_scrape_cost_usd))

    with st.expander(f"Apify run details ({len(runs)} actor run(s))", expanded=False):
        _render_run_table(runs)


def render_apify_cost_sidebar(settings: Settings, *, recent_limit: int = 50) -> None:
    """Compact Apify spend summary for the corpus sidebar."""
    runs = load_apify_runs(settings, limit=recent_limit)
    if not runs:
        st.caption("Apify spend: no runs logged yet.")
        return
    summary = summarize_apify_runs(runs)
    st.metric(
        f"Apify spend (last {summary.run_count} runs)",
        _format_cost(summary.total_cost_usd),
        help="Sum of usageTotalUsd from logged Apify actor runs (post search + profile scrape).",
    )
    st.caption(
        f"Posts {_format_cost(summary.post_search_cost_usd)} · "
        f"Profiles {_format_cost(summary.profile_scrape_cost_usd)}"
    )


def render_apify_cost_history(settings: Settings, *, limit: int = 30) -> None:
    """Full Apify cost history panel."""
    runs = load_apify_runs(settings, limit=limit)
    if not runs:
        st.info("No Apify runs logged yet. Costs appear after scraper runs on the Scraper Stage or Validation Collect pages.")
        return
    summary = summarize_apify_runs(runs)
    st.subheader("Apify Spend History")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total (recent)", _format_cost(summary.total_cost_usd))
    c2.metric("Post search", _format_cost(summary.post_search_cost_usd))
    c3.metric("Profile scrape", _format_cost(summary.profile_scrape_cost_usd))
    c4.metric("Runs logged", summary.run_count)
    _render_run_table(list(reversed(runs)))


def _render_run_table(runs: list[ApifyRunRecord]) -> None:
    rows = []
    for run in runs:
        rows.append(
            {
                "When": run.recorded_at.strftime("%Y-%m-%d %H:%M"),
                "Scraper": run.scraper.replace("_", " "),
                "Status": run.status,
                "Items": run.item_count,
                "Cost": _format_cost(run.cost_usd),
                "CU": f"{run.compute_units:.3f}" if run.compute_units is not None else "—",
                "Context": run.context or "—",
                "Run ID": run.run_id[:12] if run.run_id else "—",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)
