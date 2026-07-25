"""Read-only derived search plan view."""

from __future__ import annotations

import streamlit as st

from phase_10.search_plan import get_search_plan


def render_plan_panel() -> None:
    st.subheader("Derived search plan")
    plan = get_search_plan()

    c1, c2, c3 = st.columns(3)
    c1.metric("Terms", len(plan.terms))
    c2.metric("Seed accounts", len(plan.seed_accounts))
    c3.metric("Niche weights", len(plan.weights_by_niche))

    if plan.stub:
        st.info(
            "Niche weights are empty until T10.2 merges user-derived niches "
            "(T10.6 taxonomy). Terms and accounts currently mirror saved seeds."
        )

    if plan.terms:
        st.markdown("**Active terms**")
        st.code("\n".join(plan.terms), language=None)
    if plan.seed_accounts:
        st.markdown("**Seed accounts**")
        st.code("\n".join(plan.seed_accounts), language=None)
    if plan.weights_by_niche:
        st.dataframe(
            [
                {"niche": niche, "weight": weight}
                for niche, weight in sorted(plan.weights_by_niche.items())
            ],
            hide_index=True,
            use_container_width=True,
        )
    elif not plan.terms and not plan.seed_accounts:
        st.caption("Save seeds above to populate the plan.")

    if plan.updated_at:
        st.caption(f"Plan updated: `{plan.updated_at}`")
