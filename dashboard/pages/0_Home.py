"""Home — project overview for new joiners."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboard.chrome import (  # noqa: E402
    page_header,
    render_how_phases_connect,
    render_phase_legend,
    section_header,
)

st.set_page_config(page_title="Home", layout="wide")

page_header(
    "ITO test harness",
    "This dashboard is the **operator console** for building a LinkedIn post "
    "corpus, scoring drafts, checking predictions against real engagement, and "
    "(carefully) learning from mistakes. It is not the end-user product UI — "
    "it is meant to be clear enough that someone new can find the right page.",
)

section_header(
    "What we are building",
    """
**Corpus path:** collect LinkedIn posts → analyse them → embed → search similar.

**Validation path:** predict engagement → wait / re-scrape → compare → save
lessons → maybe adjust future predictions.

**Evaluation:** paste a draft and get a score + rewrite suggestions (uses the
same retrieval + agents as production-shaped code).
""",
)
st.markdown(
    """
| Area | In plain English | Nav group |
|------|------------------|-----------|
| **Build the corpus** | Gather and prepare historical posts | Build the corpus |
| **Check and learn** | Predict, grade, and improve | Check and learn |
| **Try it** | Score a draft you write | Try it |
| **Documents** | Planning notes and cheat sheets | Start here |
"""
)

section_header(
    "How the pieces connect",
    """
Think of a loop: **predict → wait for real numbers → grade → learn → predict better**.

Learning switches (calibration / injection) stay **off in production** until
an offline test (Phase F) shows a clear improvement.
""",
)
st.markdown(
    """
```text
Collect posts  →  Analyse  →  Embed  →  Search / Evaluate drafts
                      ↓
              Collect & predict
                      ↓
              Validation queue (~48h or force)
                      ↓
              Accuracy + Feedback loop (lessons, optional learning)
```
"""
)
render_how_phases_connect()

section_header(
    "Phases A–J (color legend)",
    """
Every colored pill on the dashboard uses this same map. Hover/`?` sections
explain the page; this table explains the **roadmap letters**.
""",
)
render_phase_legend()

section_header(
    "Where should I click?",
    "Quick routes depending on what you came to do today.",
)
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("**New to the project**")
    st.markdown(
        "1. Read **Documents**\n"
        "2. Skim this Home legend\n"
        "3. Open **Feedback loop** and read the `?` boxes — do not flip switches"
    )
with c2:
    st.markdown("**Testing the corpus**")
    st.markdown(
        "1. **Collect samples**\n"
        "2. **Analyse posts** (start with Stage 1, or a small N for Stage 2)\n"
        "3. **Make embeddings** → **Search similar**"
    )
with c3:
    st.markdown("**Operating validation**")
    st.markdown(
        "1. **Collect and predict**\n"
        "2. **Validation queue** (grade)\n"
        "3. **Accuracy over time** / **Feedback loop**\n"
        "4. Keep calibration & injection **OFF** until Phase F is GO"
    )

st.info(
    "Tip: every major section has a **?** button with a plain-English explanation. "
    "Use those before changing settings."
)
