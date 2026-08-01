"""Minimal Streamlit chrome helpers for feedback UI panels.

Kept inside ``feedback/`` so the backend does not depend on the separate
``dashboard-for-devs`` Streamlit repo. Full page chrome lives in that repo.
"""

from __future__ import annotations

from typing import Sequence

import streamlit as st

# Subset of dashboard.chrome.PHASES used by feedback panels.
PHASES: dict[str, dict[str, str]] = {
    "0": {"name": "Foundation", "color": "#64748b"},
    "A": {"name": "Calibration", "color": "#2563eb"},
    "B": {"name": "Lessons", "color": "#0d9488"},
    "C": {"name": "Buckets", "color": "#16a34a"},
    "D": {"name": "Injection", "color": "#d97706"},
    "E": {"name": "Observability", "color": "#4f46e5"},
    "F": {"name": "Prove lift", "color": "#dc2626"},
    "G": {"name": "Smarter lessons", "color": "#7c3aed"},
    "H": {"name": "Meaning match", "color": "#0891b2"},
    "I": {"name": "Scale", "color": "#a16207"},
    "J": {"name": "Injectability", "color": "#db2777"},
    "G+": {"name": "Auto-approve", "color": "#9333ea"},
}


def section_header(title: str, help_markdown: str) -> None:
    """Subheader with a ? popover explaining the section."""
    left, right = st.columns([0.93, 0.07])
    with left:
        st.subheader(title)
    with right:
        with st.popover("?"):
            st.markdown(help_markdown)


def phase_badge_html(letter: str, *, show_name: bool = True) -> str:
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
    html = "".join(phase_badge_html(letter) for letter in letters if letter in PHASES)
    if html:
        st.markdown(html, unsafe_allow_html=True)
