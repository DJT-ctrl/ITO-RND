"""Agentic — ops control plane for background automation (T10.1 / T10.2)."""

import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from config.settings import load_settings  # noqa: E402
from dashboard.chrome import page_header  # noqa: E402
from phase_10.ui import render_agentic_layer  # noqa: E402

st.set_page_config(page_title="Agentic layer", layout="wide")
page_header(
    "Agentic layer",
    "Configure and observe **scheduled background automation**: seed search "
    "plan, niche weights, job flags, budget, and Pro digests. This tab does "
    "**not** reimplement scrape or eval — it calls shared Phase 10 services.",
    step_hint="Phase 10 · Ops only · Manual scrape stays on Collect samples",
)

settings = load_settings()
if not settings.database_url:
    st.warning("DATABASE_URL is not set — search plan seeds and rebuild need Postgres.")
    st.stop()

render_agentic_layer()
