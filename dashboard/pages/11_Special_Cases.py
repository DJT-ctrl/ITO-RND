"""Special cases — review libraries outside the live feedback score path.

A1 post-mortems live here. A2 trends can attach later without bloating
feedback-loop pages.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from config.settings import load_settings
from post_mortems.ui import render_post_mortems_section

st.title("Special cases")
st.caption(
    "Offline case-study libraries (anomaly post-mortems, later trends / "
    "percentile extremes). These are for review and suggestions — they do "
    "not change calibration or injection scores."
)

settings = load_settings()
limit = st.sidebar.number_input("Rows to load", min_value=5, max_value=200, value=50)
render_post_mortems_section(settings, limit=int(limit))
