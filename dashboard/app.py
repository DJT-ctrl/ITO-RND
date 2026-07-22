"""Streamlit test harness entry point.

Run with:
    streamlit run dashboard/app.py

Navigation groups are set here: Start here, Build the corpus, Check and learn,
Try it. Page chrome (headers, phase colors, ? help) lives in dashboard/chrome.py.
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from dashboard.invite_gate import invite_configured, require_invite

_PAGES = Path(__file__).resolve().parent / "pages"
_VALIDATION = _PAGES / "validation"

st.set_page_config(page_title="ITO Test Harness", layout="wide")

# Password first on shared demos; after unlock the harness below is unchanged.
if invite_configured():
    require_invite()

pg = st.navigation(
    {
        "Start here": [
            st.Page(
                str(_PAGES / "0_Home.py"),
                title="Home",
                icon=":material/home:",
                default=True,
            ),
            st.Page(
                str(_PAGES / "0_Documents.py"),
                title="Documents",
                icon=":material/description:",
            ),
        ],
        "Build the corpus": [
            st.Page(
                str(_PAGES / "1_Scraper_Stage.py"),
                title="Collect samples",
                icon=":material/search:",
            ),
            st.Page(
                str(_PAGES / "2_Post_Analyser.py"),
                title="Analyse posts",
                icon=":material/analytics:",
            ),
            st.Page(
                str(_PAGES / "3_Pattern_Analysis.py"),
                title="Find patterns",
                icon=":material/insights:",
            ),
            st.Page(
                str(_PAGES / "4_Vectorisation.py"),
                title="Make embeddings",
                icon=":material/grid_on:",
            ),
            st.Page(
                str(_PAGES / "5_Similarity_Search.py"),
                title="Search similar",
                icon=":material/manage_search:",
            ),
        ],
        "Check and learn": [
            st.Page(
                str(_VALIDATION / "7_Validation_Collect.py"),
                title="Collect and predict",
                icon=":material/download:",
            ),
            st.Page(
                str(_VALIDATION / "8_Validation_Queue.py"),
                title="Validation queue",
                icon=":material/schedule:",
            ),
            st.Page(
                str(_VALIDATION / "9_Accuracy_History.py"),
                title="Accuracy over time",
                icon=":material/monitoring:",
            ),
            st.Page(
                str(_VALIDATION / "10_Feedback_Loop.py"),
                title="Feedback loop",
                icon=":material/sync:",
            ),
        ],
        "Try it": [
            st.Page(
                str(_PAGES / "6_Evaluation_Cycle.py"),
                title="Draft evaluator",
                icon=":material/check_circle:",
            ),
        ],
    },
    position="top",
)
pg.run()
