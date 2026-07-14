"""Streamlit UI for evaluation-cycle cost/latency telemetry."""

from __future__ import annotations

from typing import Optional

import streamlit as st

from config.settings import Settings
from telemetry.gemini_cost import summarize_gemini_cost
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


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,}"


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
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Gemini Cost (est.)", _format_cost(metadata.total_cost_usd))
    m2.metric("Total Latency", _format_latency(metadata.total_latency_ms))
    m3.metric(
        "Total Tokens",
        _format_tokens(total_tokens),
        help=(
            f"Input: {metadata.total_input_tokens:,} · "
            f"Output: {metadata.total_output_tokens:,}"
        ),
    )
    m4.metric(
        "In / Out",
        f"{_format_tokens(metadata.total_input_tokens)} / {_format_tokens(metadata.total_output_tokens)}",
        help="Input tokens (prompt) vs output tokens (completion) breakdown.",
    )

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


# ── Overall Gemini cost (aggregate across all evaluation runs) ──────────────


def render_gemini_cost_sidebar(settings: Settings, *, recent_limit: int = 50) -> None:
    """Compact Gemini spend summary for the corpus sidebar."""
    summary = summarize_gemini_cost(settings, limit=recent_limit)
    if summary.run_count == 0:
        st.caption("Gemini spend: no evaluation runs logged yet.")
        return
    st.metric(
        f"Gemini spend (est.) — {summary.run_count} runs",
        _format_cost(summary.total_cost_usd),
        help=(
            f"Estimated USD cost from {summary.run_count} logged evaluation run(s). "
            f"Total tokens: {summary.total_tokens:,} "
            f"(in: {summary.total_input_tokens:,} / out: {summary.total_output_tokens:,})."
        ),
    )
    st.caption(
        f"{_format_tokens(summary.total_input_tokens)} in · "
        f"{_format_tokens(summary.total_output_tokens)} out · "
        f"{summary.llm_step_count} LLM calls · "
        f"{summary.embedding_step_count} embeddings"
    )


def render_gemini_cost_history(settings: Settings, *, limit: int = 50) -> None:
    """Full Gemini cost history panel with per-run breakdown table."""
    from telemetry.gemini_cost import load_eval_runs

    runs = load_eval_runs(settings, limit=limit)
    if not runs:
        st.info(
            "No Gemini evaluation runs logged yet. "
            "Costs appear after running an evaluation on the Evaluation Cycle page."
        )
        return

    summary = summarize_gemini_cost(settings, limit=limit)
    st.subheader("Gemini Spend History (Estimated)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Cost (est.)", _format_cost(summary.total_cost_usd))
    c2.metric(
        "Total Tokens",
        _format_tokens(summary.total_tokens),
        help=f"In: {summary.total_input_tokens:,} / Out: {summary.total_output_tokens:,}",
    )
    c3.metric("LLM Calls", summary.llm_step_count)
    c4.metric("Runs Logged", summary.run_count)

    # Per-run breakdown table
    rows = []
    for run in runs:
        run_id = run.get("run_id", "?")[:8]
        started = run.get("started_at", "—")
        if isinstance(started, str) and len(started) > 16:
            started = started[:16].replace("T", " ")
        in_tok = int(run.get("total_input_tokens", 0))
        out_tok = int(run.get("total_output_tokens", 0))
        cost = float(run.get("total_cost_usd", 0.0))
        model = run.get("agent_model", "—")
        steps = len(run.get("steps", []))
        rows.append(
            {
                "Run": run_id,
                "When": started,
                "Model": model or "—",
                "In Tokens": f"{in_tok:,}",
                "Out Tokens": f"{out_tok:,}",
                "Total Tokens": f"{in_tok + out_tok:,}",
                "Cost (est.)": _format_cost(cost),
                "Steps": steps,
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)
