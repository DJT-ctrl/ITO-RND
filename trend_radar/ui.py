"""Streamlit helpers for Special Cases — A2 trends section."""

from __future__ import annotations

from typing import Any

import streamlit as st

from config.settings import Settings
from storage.vector_store import create_schema, get_connection
from trend_radar.store import list_trends


def render_trends_section(settings: Settings, *, limit: int = 50) -> None:
    st.subheader("Corpus trend radar (A2)")
    st.caption(
        "Week-over-week topic clusters from your scraped embeddings. "
        "Suggestion / digest input — does not change live prediction scores. "
        "Time axis: posts.inserted_at (no posted_at on posts)."
    )
    if not settings.database_url:
        st.warning("DATABASE_URL is not set.")
        return

    try:
        with get_connection(settings) as conn:
            create_schema(conn)
            rows = list_trends(conn, limit=limit)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not load trends: {exc}")
        return

    if not rows:
        st.info(
            "No trends yet. Run: "
            "`python -m trend_radar.jobs.run_trend_radar --skip-llm-labels`"
        )
        return

    st.dataframe(_table_rows(rows), use_container_width=True, hide_index=True)


def _table_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "week_start": r["week_start"],
            "label": r["label"],
            "cluster_id": r["cluster_id"],
            "post_count": r["post_count"],
            "share": round(r["share_of_corpus"], 3),
            "growth_rate": r["growth_rate"],
            "mean_engagement": (
                None
                if r["mean_total_engagement"] is None
                else round(r["mean_total_engagement"], 1)
            ),
        }
        for r in rows
    ]
