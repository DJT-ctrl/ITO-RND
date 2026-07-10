"""Streamlit test harness entry point.

Run with:
    streamlit run dashboard/app.py

Page labels in the sidebar are set here via st.navigation — the entry file
stays ``app.py`` (standard Streamlit convention) while the first tab shows
as "Scraper Stage" instead of "app".
"""

from pathlib import Path

import streamlit as st

_PAGES = Path(__file__).resolve().parent / "pages"

st.set_page_config(page_title="ITO Test Harness", layout="wide")

pg = st.navigation(
    [
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
        st.Page(
            str(_PAGES / "6_Evaluation_Cycle.py"),
            title="Evaluation Cycle",
            icon="✅",
        ),
    ]
)
pg.run()
