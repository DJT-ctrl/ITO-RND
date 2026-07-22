"""Documents — hardcoded planning notes and cheat sheets."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboard.chrome import page_header, section_header  # noqa: E402
from dashboard.documents_catalog import DOCUMENTS, get_document  # noqa: E402

st.set_page_config(page_title="Documents", layout="wide")

page_header(
    "Documents",
    "Planning notes and onboarding material, written for humans. "
    "Entries are **hardcoded** in the repo — paste new content in chat when you "
    "want something added.",
)

section_header(
    "Browse",
    """
Pick a document on the left. Placeholders marked *(paste later)* are reserved
slots for notes you will submit. Filled docs include **Phases A–J** and the
**Feedback loop Q&A** operator notes.
""",
)

labels = {
    doc.id: (
        f"{doc.title}"
        + ("  ·  " + ", ".join(doc.tags) if doc.tags else "")
    )
    for doc in DOCUMENTS
}
ids = list(labels.keys())

left, right = st.columns([0.34, 0.66])
with left:
    selected_id = st.radio(
        "Documents",
        options=ids,
        format_func=lambda i: labels[i],
        label_visibility="collapsed",
    )
with right:
    doc = get_document(selected_id)
    if doc is None:
        st.warning("Document not found.")
    else:
        st.subheader(doc.title)
        st.caption(doc.plain_summary)
        if doc.tags:
            st.caption("Tags: " + ", ".join(doc.tags))
        st.markdown(doc.body_markdown)
