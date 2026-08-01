"""Read-only derived search plan view + rebuild action."""

from __future__ import annotations

import streamlit as st

from phase_10.search_plan import SearchPlanError, get_search_plan, rebuild_search_plan


def render_plan_panel() -> None:
    st.subheader("Derived search plan")

    try:
        plan = get_search_plan()
    except SearchPlanError as exc:
        st.warning(str(exc))
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Terms", len(plan.terms))
    c2.metric("Seed accounts", len(plan.seed_accounts))
    c3.metric("Niche weights", len(plan.weights_by_niche))

    if st.button("Rebuild plan", key="agentic_rebuild_plan"):
        try:
            plan = rebuild_search_plan()
        except SearchPlanError as exc:
            st.error(str(exc))
            return
        st.success(
            f"Plan rebuilt — {len(plan.weights_by_niche)} niche weight(s) "
            f"from subscriber-tagged posts."
        )
        st.rerun()

    if not plan.weights_by_niche:
        st.caption(
            "No niche weights yet — need subscriber posts (`posts.user_id`) "
            "with a tagged `niche`. Seeds still drive general refresh."
        )

    if plan.terms:
        st.markdown("**Active terms**")
        st.code("\n".join(plan.terms), language=None)
    if plan.seed_accounts:
        st.markdown("**Seed accounts**")
        st.code("\n".join(plan.seed_accounts), language=None)
    if plan.weights_by_niche:
        st.markdown("**Niche weights** (share of users by primary niche)")
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
