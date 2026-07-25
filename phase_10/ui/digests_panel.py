"""Pro workflow digests (T10.10)."""

from __future__ import annotations

import streamlit as st

from phase_10.digests import list_digests


def render_digests_panel() -> None:
    st.subheader("Pro digests")
    st.caption(
        "Daily read-only Gemini Pro critiques of logs and telemetry (T10.10). "
        "Nothing is auto-applied to config."
    )

    digests = list_digests(limit=10)
    if not digests:
        st.info("No digests yet — awaiting T10.10.")
        return

    for digest in digests:
        with st.expander(f"{digest.created_at} · {digest.model}", expanded=False):
            st.markdown(digest.summary)
            st.caption(f"id: `{digest.id}`")
