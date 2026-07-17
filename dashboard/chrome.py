"""Shared Streamlit chrome: headers, ? help, phase badges, pipeline strips.

Frontend-only helpers. No backend calls.
"""

from __future__ import annotations

from typing import Literal, Optional, Sequence

import streamlit as st

# Fixed palette for Phase 0 / A–J (+ G+). Used everywhere for consistency.
PHASES: dict[str, dict[str, str]] = {
    "0": {
        "name": "Foundation",
        "plain": "Grade predictions after real engagement comes in",
        "color": "#64748b",
        "status": "Done",
    },
    "A": {
        "name": "Calibration",
        "plain": "Nudge predicted scores using past mistakes",
        "color": "#2563eb",
        "status": "Done (prod OFF)",
    },
    "B": {
        "name": "Lessons",
        "plain": "Write a short lesson after each graded post",
        "color": "#0d9488",
        "status": "Done",
    },
    "C": {
        "name": "Buckets",
        "plain": "Sort posts into length × format × audience groups",
        "color": "#16a34a",
        "status": "Done",
    },
    "D": {
        "name": "Injection",
        "plain": "Show recent same-bucket lessons to the predictor",
        "color": "#d97706",
        "status": "Done (prod OFF)",
    },
    "E": {
        "name": "Observability",
        "plain": "Measure accuracy, costs, and learning health",
        "color": "#4f46e5",
        "status": "Done",
    },
    "F": {
        "name": "Prove lift",
        "plain": "Offline test: only turn learning on if error drops enough",
        "color": "#dc2626",
        "status": "NO-GO (keep OFF)",
    },
    "G": {
        "name": "Smarter lessons",
        "plain": "LLM “why” text + human approve/reject before use",
        "color": "#7c3aed",
        "status": "Done (staging)",
    },
    "H": {
        "name": "Meaning match",
        "plain": "Route by embedding similarity (centroids), not only labels",
        "color": "#0891b2",
        "status": "Done (staging)",
    },
    "I": {
        "name": "Scale",
        "plain": "Background job queue + short cluster summaries",
        "color": "#a16207",
        "status": "Done",
    },
    "J": {
        "name": "Injectability",
        "plain": "Shadow mode and softer locks so lessons can move the score",
        "color": "#db2777",
        "status": "Done (hard lock live)",
    },
    "G+": {
        "name": "Auto-approve",
        "plain": "Optionally auto-approve trusted LLM lessons",
        "color": "#9333ea",
        "status": "Done (default OFF)",
    },
}

CorpusStep = Literal["collect", "analyse", "patterns", "embed", "search"]
ValidationStep = Literal["predict", "queue", "accuracy", "feedback"]

_CORPUS_STEPS: Sequence[tuple[CorpusStep, str]] = (
    ("collect", "1 · Collect"),
    ("analyse", "2 · Analyse"),
    ("patterns", "3 · Patterns"),
    ("embed", "4 · Embed"),
    ("search", "5 · Search"),
)

_VALIDATION_STEPS: Sequence[tuple[ValidationStep, str]] = (
    ("predict", "1 · Predict"),
    ("queue", "2 · Queue"),
    ("accuracy", "3 · Accuracy"),
    ("feedback", "4 · Feedback"),
)


def section_header(title: str, help_markdown: str) -> None:
    """Subheader with a ? popover explaining the section."""
    left, right = st.columns([0.93, 0.07])
    with left:
        st.subheader(title)
    with right:
        with st.popover("?"):
            st.markdown(help_markdown)


def page_header(
    title: str,
    plain_summary: str,
    *,
    step_hint: Optional[str] = None,
) -> None:
    """Standard page title + plain-English purpose line."""
    st.title(title)
    st.markdown(plain_summary)
    if step_hint:
        st.caption(step_hint)


def phase_badge_html(letter: str, *, show_name: bool = True) -> str:
    """Single colored phase pill (HTML fragment)."""
    meta = PHASES.get(letter)
    if not meta:
        return ""
    label = f"{letter} · {meta['name']}" if show_name else letter
    return (
        f'<span style="display:inline-block;padding:2px 10px;margin:2px 4px 2px 0;'
        f"border-radius:999px;background:{meta['color']};color:#fff;"
        f'font-size:0.78rem;font-weight:600;letter-spacing:0.02em;">'
        f"{label}</span>"
    )


def render_phase_badges(letters: Sequence[str]) -> None:
    """Render one or more phase pills."""
    html = "".join(phase_badge_html(letter) for letter in letters if letter in PHASES)
    if html:
        st.markdown(html, unsafe_allow_html=True)


def render_phase_legend(*, compact: bool = False) -> None:
    """Full A–J (+0, G+) legend with plain English and status."""
    keys = ["0", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "G+"]
    if compact:
        html = "".join(phase_badge_html(k) for k in keys)
        st.markdown(html, unsafe_allow_html=True)
        return

    rows = []
    for key in keys:
        meta = PHASES[key]
        badge = phase_badge_html(key)
        rows.append(
            f"<tr>"
            f"<td style='padding:6px 10px;vertical-align:top;white-space:nowrap;'>"
            f"{badge}</td>"
            f"<td style='padding:6px 10px;vertical-align:top;'>{meta['plain']}</td>"
            f"<td style='padding:6px 10px;vertical-align:top;color:#475569;'>"
            f"<em>{meta['status']}</em></td>"
            f"</tr>"
        )
    st.markdown(
        "<table style='width:100%;border-collapse:collapse;font-size:0.92rem;'>"
        "<thead><tr>"
        "<th style='text-align:left;padding:6px 10px;'>Phase</th>"
        "<th style='text-align:left;padding:6px 10px;'>What it does</th>"
        "<th style='text-align:left;padding:6px 10px;'>Status</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>",
        unsafe_allow_html=True,
    )


def pipeline_flow_strip(
    kind: Literal["corpus", "validation"],
    current: str,
) -> None:
    """You-are-here strip for corpus or validation steps."""
    steps = _CORPUS_STEPS if kind == "corpus" else _VALIDATION_STEPS
    parts: list[str] = []
    for key, label in steps:
        active = key == current
        bg = "#1f5f8b" if active else "#e2e8f0"
        fg = "#ffffff" if active else "#334155"
        weight = "700" if active else "500"
        parts.append(
            f'<span style="display:inline-block;padding:6px 12px;margin:2px 4px;'
            f"border-radius:8px;background:{bg};color:{fg};font-size:0.82rem;"
            f'font-weight:{weight};">{label}</span>'
        )
    joiner = (
        '<span style="color:#94a3b8;margin:0 2px;font-weight:600;">→</span>'
    )
    st.markdown(joiner.join(parts), unsafe_allow_html=True)


def render_how_phases_connect() -> None:
    """Short plain-English A→J story for Home / Feedback."""
    st.markdown(
        """
1. We **predict** how a post will do, then later **check** the real numbers (**0**).
2. We can **nudge scores** from past errors (**A**) and **save lessons** (**B**).
3. Lessons are filed into **buckets** (**C**) and can be **shown to the predictor** (**D**).
4. We **measure** carefully (**E**) and only ship learning if an offline test says so (**F**).
5. Richer lessons (**G**), meaning-based routing (**H**), a job queue (**I**), and
   shadow / softer locks (**J**) deepen the loop — but live calibration / injection
   stay off until **F** is GO.
"""
    )
    render_phase_badges(["0", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J"])
