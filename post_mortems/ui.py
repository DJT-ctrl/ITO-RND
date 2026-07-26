"""Streamlit helpers for the Special Cases page (A1 post-mortems)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from config.settings import Settings
from post_mortems.store import list_post_mortems
from storage.vector_store import create_schema, get_connection


def render_post_mortems_section(settings: Settings, *, limit: int = 50) -> None:
    st.subheader("Anomaly post-mortems (A1)")
    st.caption(
        "Case studies for posts flagged by engagement-ratio anomaly detection. "
        "Suggestion / review library — does not change live prediction scores."
    )
    if not settings.database_url:
        st.warning("DATABASE_URL is not set.")
        return

    try:
        with get_connection(settings) as conn:
            create_schema(conn)
            rows = list_post_mortems(conn, limit=limit)
    except Exception as exc:  # noqa: BLE001 — show in UI
        st.error(f"Could not load post_mortems: {exc}")
        return

    if not rows:
        st.info(
            "No post-mortems yet. Run: "
            "`python -m post_mortems.jobs.run_post_mortems --limit 50`"
        )
        return

    st.dataframe(_table_rows(rows), use_container_width=True, hide_index=True)

    selected = st.selectbox(
        "Inspect post-mortem",
        options=[r["post_id"] for r in rows],
        format_func=lambda pid: pid,
    )
    detail = next((r for r in rows if r["post_id"] == selected), None)
    if detail:
        st.markdown(f"**Verdict:** `{detail['verdict']}`")
        st.markdown(f"**Machine reasons:** {', '.join(detail['machine_reasons']) or '—'}")
        st.write(detail["summary"])
        st.markdown(f"**Lesson for models:** {detail['lesson_for_models']}")
        with st.expander("Evidence"):
            st.json(detail["evidence"])


def _table_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "post_id": r["post_id"],
            "verdict": r["verdict"],
            "reasons": ", ".join(r["machine_reasons"]),
            "generated_at": str(r["generated_at"]),
            "summary": (r["summary"][:120] + "…") if len(r["summary"]) > 120 else r["summary"],
        }
        for r in rows
    ]
