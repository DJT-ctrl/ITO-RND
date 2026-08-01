"""Scrape proof / run-health panel (T10.5.5)."""

from __future__ import annotations

import json

import streamlit as st

from phase_10.scrape_proofs import list_scrape_proofs


def render_proof_panel() -> None:
    st.subheader("Scrape proof")
    st.caption(
        "Multi-signal health for each corpus refresh (yield, mix, cost, waste, "
        "freshness). Written by T10.4 / T10.5 — not a separate cron."
    )
    proofs = list_scrape_proofs(limit=20)
    if not proofs:
        st.info("No scrape proofs yet. Run a general or niche refresh tick.")
        return

    rows = [
        {
            "When": p.created_at or "—",
            "Job": p.job_id,
            "Niche": p.niche or "—",
            "OK": "yes" if p.ok else "no",
            "Summary": p.summary,
            "New": p.payload.get("new", "—"),
            "Scraped": p.payload.get("scraped", "—"),
            "USD": p.payload.get("apify_usd", "—"),
            "Overlap %": p.payload.get("overlap_pct", "—"),
        }
        for p in proofs
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)

    with st.expander("Latest proof payload", expanded=False):
        st.code(json.dumps(proofs[0].payload, indent=2, default=str), language="json")
