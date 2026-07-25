"""Agentic — ops control plane for background automation (T10.1)."""

import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from dashboard.chrome import page_header  # noqa: E402
from phase_10.ui import render_agentic_layer  # noqa: E402

st.set_page_config(page_title="Agentic layer", layout="wide")
page_header(
    "Agentic layer",
    "Configure and observe **scheduled background automation**: seed search "
    "plan, job flags, budget, and Pro digests. This tab does **not** "
    "reimplement scrape or eval — it calls shared services (stubs until "
    "T10.2–T10.10 fill them in).",
    step_hint="Phase 10 · Ops only · Manual scrape stays on Collect samples",
)

render_agentic_layer()
