"""Streamlit helpers for reviewing stored-post feedback."""

from __future__ import annotations

from typing import Any

import streamlit as st

from config.settings import Settings
from post_feedback.schemas import ReviewStatus
from post_feedback.store import list_post_feedback, set_review_status
from storage.vector_store import create_schema, get_connection


def render_post_feedback_section(settings: Settings, *, limit: int = 50) -> None:
    st.subheader("Stored post feedback")
    st.caption(
        "Detailed write-ups for clean labelled posts. "
        "Review library only — does not change live prediction scores."
    )
    if not settings.database_url:
        st.warning("DATABASE_URL is not set.")
        return

    try:
        with get_connection(settings) as conn:
            create_schema(conn)
            rows = list_post_feedback(conn, limit=limit)
    except Exception as exc:  # noqa: BLE001 — show in UI
        st.error(f"Could not load post_feedback: {exc}")
        return

    if not rows:
        st.info(
            "No stored-post feedback yet. Run: "
            "`python -m post_feedback.jobs.run_post_feedback --limit 50`"
        )
        return

    st.dataframe(_table_rows(rows), use_container_width=True, hide_index=True)

    selected = st.selectbox(
        "Inspect post feedback",
        options=[r["post_id"] for r in rows],
        format_func=lambda pid: pid,
    )
    detail = next((r for r in rows if r["post_id"] == selected), None)
    if not detail:
        return

    st.markdown(f"**Review:** `{detail['review_status']}`")
    if detail.get("reviewed_by"):
        st.caption(f"Reviewed by {detail['reviewed_by']}")
    st.write(detail["summary"])
    st.markdown("**What worked**")
    for item in detail["what_worked"] or ["—"]:
        st.markdown(f"- {item}")
    st.markdown("**What to change**")
    for item in detail["what_to_change"] or ["—"]:
        st.markdown(f"- {item}")
    with st.expander("Neighbor comparison"):
        st.json(detail["neighbor_notes"])
    with st.expander("Evidence"):
        st.json(detail["evidence"])

    approve, reject = st.columns(2)
    if approve.button("Approve", key=f"post_feedback_approve_{selected}"):
        _set_status(settings, selected, "approved")
    if reject.button("Reject", key=f"post_feedback_reject_{selected}"):
        _set_status(settings, selected, "rejected")


def _set_status(settings: Settings, post_id: str, status: ReviewStatus) -> None:
    try:
        with get_connection(settings) as conn:
            updated = set_review_status(
                conn,
                post_id,
                status,
                reviewed_by="dashboard",
            )
    except Exception as exc:  # noqa: BLE001 — show in UI
        st.error(f"Could not update review status: {exc}")
        return
    if not updated:
        st.warning(f"No feedback row for {post_id}.")
        return
    st.rerun()


def _table_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for row in rows:
        summary = row["summary"]
        table.append(
            {
                "post_id": row["post_id"],
                "review_status": row["review_status"],
                "generated_at": str(row["generated_at"]),
                "summary": (summary[:120] + "…") if len(summary) > 120 else summary,
            }
        )
    return table
