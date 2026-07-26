"""Evaluation Cycle — Stage 5 synthesis optimisation (T7.14–T7.16) UI."""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st
from pydantic import BaseModel

from agents.synthesis.schemas import SynthesisResult


def render_synthesis_sidebar_controls(*, missing_config: bool, draft_content: str) -> bool:
    """Sidebar explanation + Run optimisation button."""
    st.divider()
    st.subheader("Synthesis optimisation")
    with st.expander("What this does", expanded=False):
        st.markdown(
            "Optional **Stage 5** side-step (T7.14–T7.16) — does **not** replace "
            "evaluate-loop variants.\n\n"
            "One Gemini call produces three specialist rewrites, then the Predictor "
            "re-scores each and a recommendation is chosen:\n\n"
            "- **Algorithmic Maximizer** — CTR / reach / virality\n"
            "- **Strategic Counter** — pre-empts C-suite objections (uses critic "
            "when available)\n"
            "- **Brand Purist** — prestige / brand-safe over raw virality\n\n"
            "Shows predicted performance and deltas vs your evaluate baseline when present."
        )
    return st.button(
        "Run optimisation",
        type="secondary",
        disabled=bool(missing_config) or not draft_content.strip(),
        use_container_width=True,
        key="run_synthesis_optimisation",
        help="Independent Stage 5 synthesis. Uses draft + optional critic/eval context.",
    )


def render_synthesis_results_panel(
    result: Any = None,
    error: Optional[str] = None,
) -> None:
    """Render synthesis recommendation + scored specialist rewrites."""
    if error:
        st.error(f"Synthesis optimisation failed: {error}")

    if result is None:
        return

    if isinstance(result, SynthesisResult):
        data = result.model_dump()
    elif isinstance(result, BaseModel):
        data = result.model_dump()
    else:
        data = dict(result)

    st.subheader("Synthesis optimisation")
    st.caption(
        "Independent Stage 5 (T7.14–T7.16) — separate from evaluate-loop variants."
    )

    rec = data.get("recommendation") or {}
    st.success(
        f"**Recommended:** `{rec.get('agent_id', '')}` — {rec.get('reason', '')}"
    )
    if data.get("critic_objection_used"):
        st.caption(f"Counter used objection: {data['critic_objection_used']}")

    for err in data.get("errors") or []:
        st.warning(err)

    variants = data.get("variants") or []
    for i, variant in enumerate(variants):
        is_rec = variant.get("agent_id") == rec.get("agent_id")
        title = variant.get("variant_name") or variant.get("agent_id")
        badge = " · recommended" if is_rec else ""
        with st.container(border=True):
            header_col, metric_col = st.columns([3, 1])
            with header_col:
                st.markdown(f"**{title}**{badge} &nbsp; `{variant.get('agent_id', '')}`")
                st.write(variant.get("rationale", ""))
            with metric_col:
                pct = variant.get("predicted_engagement_percentile", 0)
                delta = variant.get("delta_percentile")
                delta_str = f"{delta:+.0f}" if delta is not None else None
                st.metric("Percentile", f"{pct:.0f}", delta=delta_str)
                st.metric(
                    "Engagements",
                    variant.get("predicted_total_engagement", "—"),
                )

            st.text_area(
                f"synth_{i}",
                value=variant.get("optimized_text", ""),
                height=110,
                label_visibility="collapsed",
            )
            if st.button(
                f"Use {title}",
                key=f"apply_synth_{variant.get('agent_id', i)}",
                type="secondary",
            ):
                st.session_state.draft_text = variant.get("optimized_text", "")
                st.session_state.eval_result = None
                st.rerun()

    st.divider()
