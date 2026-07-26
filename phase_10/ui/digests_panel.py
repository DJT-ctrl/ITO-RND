"""Pro workflow digests (T10.10)."""

from __future__ import annotations

import streamlit as st

from config.settings import load_settings
from phase_10.budget import allow_paid_step
from phase_10.digests import list_digests, run_pro_digest


def render_digests_panel() -> None:
    st.subheader("Pro digests")
    st.caption(
        "Daily read-only Gemini Pro critiques of logs and telemetry (T10.10). "
        "Nothing is auto-applied to config."
    )

    settings = load_settings()
    col_run, col_hint = st.columns([1, 3])
    with col_run:
        run_clicked = st.button("Run digest now", type="primary")
    with col_hint:
        st.caption(
            f"Model: `{settings.agentic_pro_digest_model}`"
            + (" · dry-run" if settings.agentic_pro_digest_dry_run else "")
        )

    if run_clicked:
        decision = allow_paid_step("pro_digest", "gemini", settings=settings)
        if not decision.allowed:
            st.warning(f"Skipped: {decision.reason}")
        else:
            with st.spinner("Building snapshot and calling Pro critic…"):
                try:
                    detail = run_pro_digest(settings)
                    st.success(detail)
                except Exception as exc:
                    st.error(f"Digest failed: {exc}")

    digests = list_digests(settings, limit=10)
    if not digests:
        st.info("No digests yet — enable the Pro digest flag or run one now.")
        return

    for digest in digests:
        title = f"{digest.created_at} · {digest.severity} · {digest.model}"
        with st.expander(title, expanded=False):
            st.markdown(digest.summary)
            findings = digest.payload.get("findings") if digest.payload else None
            if isinstance(findings, list) and findings:
                rows = [
                    {
                        "title": f.get("title", ""),
                        "severity": f.get("severity", ""),
                        "category": f.get("category", ""),
                        "suggested_action": f.get("suggested_action", ""),
                    }
                    for f in findings
                    if isinstance(f, dict)
                ]
                if rows:
                    st.dataframe(rows, hide_index=True, use_container_width=True)
            warning = digest.payload.get("budget_warning") if digest.payload else None
            if warning:
                st.warning(str(warning))
            st.caption(f"id: `{digest.id}`")
