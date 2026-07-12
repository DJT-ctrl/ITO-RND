"""Streamlit UI for evaluation-cycle cost/latency telemetry."""

from __future__ import annotations

from typing import Optional

import streamlit as st

from telemetry.schemas import RunMetadata, StepTelemetry
from telemetry.thresholds import steps_for_stage

_STAGE_ORDER = ("retrieval", "setup", "agent", "variant")
_STAGE_LABELS = {
    "retrieval": "Retrieval",
    "setup": "Setup",
    "agent": "Agents",
    "variant": "Variants",
}


def _format_latency(ms: float) -> str:
    if ms >= 1000:
        return f"{ms / 1000:.1f}s"
    return f"{ms:.0f}ms"


def _format_cost(usd: float) -> str:
    if usd < 0.01:
        return f"${usd:.4f}"
    return f"${usd:.3f}"


def render_run_metadata_summary(metadata: Optional[RunMetadata]) -> None:
    """Render cost/latency summary and per-step breakdown."""
    if metadata is None:
        return

    st.subheader("Cost & Latency")

    for warning in metadata.warnings:
        severity = "error" if warning.code == "cost_threshold" else "warning"
        if severity == "error":
            st.error(warning.message)
        else:
            st.warning(warning.message)

    total_tokens = metadata.total_input_tokens + metadata.total_output_tokens
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Cost", _format_cost(metadata.total_cost_usd))
    m2.metric("Total Latency", _format_latency(metadata.total_latency_ms))
    m3.metric("Total Tokens", f"{total_tokens:,}")

    st.caption(
        f"Run `{metadata.run_id[:8]}` · "
        f"Agent model: `{metadata.agent_model or 'unknown'}` · "
        f"Concurrent agent steps show individual wall-clock latency; "
        f"stage latency uses critical-path (max) within each parallel group."
    )

    with st.expander(f"Step breakdown ({len(metadata.steps)} steps)", expanded=False):
        for stage in _STAGE_ORDER:
            stage_steps = steps_for_stage(metadata.steps, stage)
            if not stage_steps:
                continue
            st.markdown(f"**{_STAGE_LABELS[stage]}**")
            _render_step_table(stage_steps)
            if stage != _STAGE_ORDER[-1]:
                st.divider()


def _render_step_table(steps: list[StepTelemetry]) -> None:
    rows = []
    for step in steps:
        status_icon = "✓" if step.status == "ok" else "✗"
        rows.append(
            {
                "Step": step.label,
                "Type": step.call_type,
                "Model": step.model or "—",
                "Latency": _format_latency(step.latency_ms),
                "In": step.input_tokens,
                "Out": step.output_tokens,
                "Cost": _format_cost(step.cost_usd),
                "Status": status_icon,
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)
