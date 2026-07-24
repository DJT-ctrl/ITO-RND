"""Evaluation Cycle — synthetic audience critic (T7.11–T7.13) UI helpers."""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st
from pydantic import BaseModel

from agents.audience_critic import AudienceCriticOutput


def render_critic_sidebar_controls(*, missing_config: bool, draft_content: str) -> bool:
    """Sidebar explanation + Run critic button. Returns whether the button was clicked."""
    st.divider()
    st.subheader("Synthetic audience critic")
    with st.expander("What this does", expanded=False):
        st.markdown(
            "Optional **independent** critique (T7.11–T7.13) — not part of the "
            "evaluate loop. One Gemini call role-plays three skeptical readers:\n\n"
            "- **C-Suite** — ROI holes, fluff, executive objections\n"
            "- **Practitioner** — tactical value for daily operators\n"
            "- **Industry peer** — credibility and originality in-market\n\n"
            "Does **not** change predicted scores, diagnostics, or variants."
        )
    return st.button(
        "Run critic",
        type="secondary",
        disabled=bool(missing_config) or not draft_content.strip(),
        use_container_width=True,
        key="run_audience_critic",
        help="Independent synthetic-audience pass. Uses the current draft only.",
    )


def render_critic_results_panel(
    critic: Any = None,
    critic_error: Optional[str] = None,
) -> None:
    """Render critic error and/or three-lens results at the top of the results tab."""
    if critic_error:
        st.error(f"Audience critic failed: {critic_error}")

    if critic is None:
        return

    st.subheader("Synthetic audience critic")
    st.caption(
        "Independent side-step (T7.11–T7.13) — does not affect scores or variants."
    )
    if isinstance(critic, AudienceCriticOutput):
        critic_data = critic.model_dump()
    elif isinstance(critic, BaseModel):
        critic_data = critic.model_dump()
    else:
        critic_data = dict(critic)

    score = critic_data.get("score", 0)
    st.metric("Critic score", f"{score:.1f}/10")
    st.markdown(f"**Overall verdict:** {critic_data.get('overall_verdict', '')}")

    c_suite = critic_data.get("c_suite") or {}
    practitioner = critic_data.get("practitioner") or {}
    peer = critic_data.get("peer") or {}
    lens_cols = st.columns(3)
    with lens_cols[0]:
        with st.expander("C-Suite", expanded=True):
            st.markdown(f"**Reaction:** {c_suite.get('reaction', '')}")
            st.markdown(f"**Primary objection:** {c_suite.get('primary_objection', '')}")
            if c_suite.get("roi_notes"):
                st.markdown(f"**ROI notes:** {c_suite['roi_notes']}")
    with lens_cols[1]:
        with st.expander("Practitioner", expanded=True):
            st.markdown(f"**Reaction:** {practitioner.get('reaction', '')}")
            st.markdown(f"**Perceived value:** {practitioner.get('perceived_value', '')}")
            if practitioner.get("tactical_gaps"):
                st.markdown(f"**Tactical gaps:** {practitioner['tactical_gaps']}")
    with lens_cols[2]:
        with st.expander("Industry peer", expanded=True):
            st.markdown(f"**Reaction:** {peer.get('reaction', '')}")
            st.markdown(f"**Credibility:** {peer.get('credibility_check', '')}")
            if peer.get("originality_notes"):
                st.markdown(f"**Originality:** {peer['originality_notes']}")
    st.divider()


def extract_primary_objection(critic: Any) -> Optional[str]:
    """Pull c_suite.primary_objection from a critic result for synthesis."""
    if critic is None:
        return None
    if isinstance(critic, AudienceCriticOutput):
        return critic.c_suite.primary_objection or None
    if isinstance(critic, BaseModel):
        data = critic.model_dump()
    elif isinstance(critic, dict):
        data = critic
    else:
        return None
    c_suite = data.get("c_suite") or {}
    objection = (c_suite.get("primary_objection") or "").strip()
    return objection or None
