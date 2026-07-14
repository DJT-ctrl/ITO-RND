"""Shared Streamlit helpers for pipeline bundle selection across dashboard steps."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import streamlit as st

from config.paths import resolve_data_path
from processors.finalize_records import list_analysed_datasets
from storage.pipeline_registry import (
    ManifestStage,
    PipelineBundle,
    list_bundles,
    load_merged_analysed_records,
)

StageFilter = Literal["analysed", "embedded", "ingested"]


def bundle_options(
    min_stage: StageFilter = "analysed",
    *,
    require_gemini: bool = False,
) -> list[PipelineBundle]:
    return list_bundles(min_stage=min_stage, require_gemini=require_gemini)


def format_bundle_option(bundle: PipelineBundle) -> str:
    return bundle.label()


def render_bundle_multiselect(
    *,
    label: str,
    min_stage: StageFilter = "analysed",
    key: str,
    help: Optional[str] = None,
    require_gemini: bool = False,
) -> list[PipelineBundle]:
    """Multi-select registered pipeline bundles that completed ``min_stage``."""
    bundles = bundle_options(min_stage=min_stage, require_gemini=require_gemini)
    if not bundles:
        st.warning(
            f"No pipeline bundles at stage `{min_stage}` or beyond. "
            "Complete the previous dashboard step first."
        )
        return []

    labels = [format_bundle_option(b) for b in bundles]
    selected_labels = st.multiselect(label, labels, key=key, help=help)
    id_by_label = {format_bundle_option(b): b for b in bundles}
    return [id_by_label[label] for label in selected_labels if label in id_by_label]


def analysed_filenames_for_bundles(bundles: list[PipelineBundle]) -> list[str]:
    names: list[str] = []
    for bundle in bundles:
        if bundle.analysed_jsonl:
            names.append(bundle.analysed_jsonl)
    return names


def load_records_from_bundles(
    bundles: list[PipelineBundle],
) -> tuple[list[dict], list[PipelineBundle]]:
    filenames = analysed_filenames_for_bundles(bundles)
    if not filenames:
        return [], bundles
    return load_merged_analysed_records(filenames)


def render_legacy_analysed_multiselect(
    *,
    label: str,
    key: str,
) -> list[str]:
    """Fallback multi-select for analysed JSONL files (includes unregistered legacy files)."""
    processed_dir = resolve_data_path("data/processed")
    files = list_analysed_datasets(processed_dir)
    if not files:
        return []
    names = [f.name for f in files]
    return st.multiselect(label, names, key=key)


def render_corpus_sidebar(settings) -> None:
    """Show which Postgres corpus Similarity Search / Evaluation Cycle query."""
    from pgvector.psycopg import register_vector

    from storage.pipeline_registry import list_bundles
    from storage.vector_store import get_connection

    st.header("Retrieval corpus")
    st.caption(
        "Similarity Search and Evaluation Cycle query **all posts ingested into "
        "Postgres** (not a filesystem CSV). Re-ingest upserts by `post_id`."
    )

    ingested = list_bundles(min_stage="ingested")
    if ingested:
        st.markdown("**Ingested bundles:**")
        for bundle in ingested[:8]:
            st.caption(
                f"`{bundle.bundle_id}` — {bundle.ingested_count or '?'} posts "
                f"from `{bundle.analysed_jsonl}`"
            )
        if len(ingested) > 8:
            st.caption(f"…and {len(ingested) - 8} more.")
    else:
        st.caption("No bundles marked ingested yet. Run `python -m processors.run_db_ingest`.")

    if not settings.database_url:
        st.warning("DATABASE_URL not set — corpus size unknown.")
        return

    try:
        from storage.vector_store import get_connection

        conn = get_connection(settings)
        try:
            register_vector(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM posts")
                row = cur.fetchone()
            total = int(row[0]) if row else 0
        finally:
            conn.close()
        st.metric("Posts in Postgres", total)
    except Exception as exc:  # noqa: BLE001 — test harness should surface DB issues
        st.warning(f"Could not query Postgres: {exc}")

    st.markdown("---")
    from telemetry.apify_ui import render_apify_cost_sidebar

    render_apify_cost_sidebar(settings)

    st.markdown("---")
    from telemetry.ui import render_gemini_cost_sidebar

    render_gemini_cost_sidebar(settings)
