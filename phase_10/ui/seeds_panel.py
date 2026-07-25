"""Edit seed search terms and LinkedIn accounts."""

from __future__ import annotations

import streamlit as st

from phase_10.search_plan import load_seeds, save_seeds


def render_seeds_panel() -> None:
    st.subheader("Seed search inputs")
    st.caption(
        "Bootstrap scrape queries before real user niches exist. "
        "Jobs will read these via the search plan service (T10.2)."
    )

    seeds = load_seeds()
    terms_text = st.text_area(
        "Seed search terms (one per line)",
        value="\n".join(seeds.seed_terms),
        height=120,
        key="agentic_seed_terms",
        help="Keyword queries for the general corpus refresh.",
    )
    accounts_text = st.text_area(
        "Seed LinkedIn accounts (one URL per line)",
        value="\n".join(seeds.seed_accounts),
        height=100,
        key="agentic_seed_accounts",
        help="Optional profile URLs to warm / simulate corpus coverage.",
    )

    col_save, col_meta = st.columns([1, 3])
    with col_save:
        if st.button("Save seeds", type="primary", key="agentic_save_seeds"):
            saved = save_seeds(seed_terms=terms_text, seed_accounts=accounts_text)
            st.success(
                f"Saved {len(saved.seed_terms)} term(s) and "
                f"{len(saved.seed_accounts)} account(s)."
            )
            st.rerun()
    with col_meta:
        if seeds.updated_at:
            st.caption(f"Last saved: `{seeds.updated_at}`")
        else:
            st.caption("No seeds saved yet.")
