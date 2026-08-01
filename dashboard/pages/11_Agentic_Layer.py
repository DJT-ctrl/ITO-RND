"""Agentic — ops control plane for background automation (T10.1 / T10.2)."""

import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from dashboard.dev_postgres_ui import require_postgres_for_page  # noqa: E402
from phase_10.ui import render_agentic_layer  # noqa: E402

st.set_page_config(page_title="Agentic Layer", layout="wide")
st.title("Agentic Layer")
st.caption(
    "Configure and observe scheduled background automation: seed search plan, "
    "niche weights, job flags, budget, and Pro digests. This tab does not "
    "reimplement scrape or eval — it calls shared Phase 10 services."
)

if not require_postgres_for_page():
    st.stop()

render_agentic_layer()
