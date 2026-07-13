"""Streamlit test harness entry point.

Run with:
    streamlit run dashboard/app.py

Page labels in the top navigation are set here via st.navigation — grouped into
Corpus Pipeline (stages 1-5), Validation Pipeline (prediction feedback loop),
and Evaluation (draft evaluation cycle).
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

_PAGES = Path(__file__).resolve().parent / "pages"
_VALIDATION = _PAGES / "validation"

st.set_page_config(page_title="ITO Test Harness", layout="wide")

pg = st.navigation(
    {
        "Corpus Pipeline": [
            st.Page(
                str(_PAGES / "1_Scraper_Stage.py"),
                title="Scraper Stage",
                icon="🔍",
                default=True,
            ),
            st.Page(
                str(_PAGES / "2_Post_Analyser.py"),
                title="Post Analyser",
                icon="📊",
            ),
            st.Page(
                str(_PAGES / "3_Pattern_Analysis.py"),
                title="Pattern Analysis",
                icon="📈",
            ),
            st.Page(
                str(_PAGES / "4_Vectorisation.py"),
                title="Vectorisation",
                icon="🧮",
            ),
            st.Page(
                str(_PAGES / "5_Similarity_Search.py"),
                title="Similarity Search",
                icon="🔎",
            ),
        ],
        "Validation Pipeline": [
            st.Page(
                str(_VALIDATION / "7_Validation_Collect.py"),
                title="Collect & Predict",
                icon="📥",
            ),
            st.Page(
                str(_VALIDATION / "8_Validation_Queue.py"),
                title="Validation Queue",
                icon="⏱️",
            ),
            st.Page(
                str(_VALIDATION / "9_Accuracy_History.py"),
                title="Accuracy History",
                icon="📉",
            ),
            st.Page(
                str(_VALIDATION / "10_Feedback_Loop.py"),
                title="Feedback Loop",
                icon="🔁",
            ),
        ],
        "Evaluation": [
            st.Page(
                str(_PAGES / "6_Evaluation_Cycle.py"),
                title="Evaluation Cycle",
                icon="✅",
            ),
        ],
    },
    position="top",
)
pg.run()
