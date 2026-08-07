"""Shared retrieval context for evaluation, validation, and rewrite workflows.

A text is embedded once, then queried for the ordinary prediction neighbors and
for a wider global candidate pool used by deterministic cross-reference
selection. The two result sets remain separate by design.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import numpy as np
from pgvector.psycopg import register_vector

from agents.schemas import resolve_neighbor_limit
from api.schemas import SimilarPost
from config.settings import Settings
from processors.embedder import EMBEDDING_MODEL_VERSION, embed_query
from storage.vector_store import find_similar, get_connection
from telemetry.collector import RunMetadataCollector
from telemetry.instrument import run_timed_thread


@dataclass
class RetrievalContext:
    """One query embedding and its ordinary plus global retrieval surfaces."""

    query_embedding: list[float]
    embedding_model_version: str
    similar_posts: list[SimilarPost]
    global_candidates: list[SimilarPost] = field(default_factory=list)
    global_candidate_error: Optional[str] = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


async def retrieve_post_context(
    text: str,
    settings: Settings,
    *,
    neighbor_limit: int = 10,
    global_candidate_limit: int = 30,
    user_id: Optional[str] = None,
    prefer_niche: Optional[str] = None,
    prefer_age_hours: Optional[float] = None,
    include_global_candidates: bool = True,
    collector: Optional[RunMetadataCollector] = None,
    telemetry_prefix: str = "retrieval",
    telemetry_stage: str = "retrieval",
    embedder: Optional[Callable[[str, Settings], tuple[np.ndarray, int]]] = None,
    connection_factory: Optional[Callable[[Settings], Any]] = None,
    similarity_finder: Optional[Callable[..., list[dict[str, Any]]]] = None,
    vector_registrar: Optional[Callable[[Any], None]] = None,
) -> RetrievalContext:
    """Embed once and retrieve ordinary neighbors plus global candidates.

    Ordinary retrieval keeps the existing tenant/fallback behavior. Cross-
    reference candidates always query the global corpus and failures there are
    isolated so callers can still complete ordinary prediction work.
    """
    resolved_neighbor_limit = resolve_neighbor_limit(neighbor_limit)
    candidate_limit = max(resolved_neighbor_limit, int(global_candidate_limit))
    resolved_embedder = embedder or embed_query
    resolved_connection_factory = connection_factory or get_connection
    resolved_similarity_finder = similarity_finder or find_similar
    resolved_vector_registrar = vector_registrar or register_vector

    def _embed() -> tuple[np.ndarray, int]:
        return resolved_embedder(text, settings)

    embedding_started_at = _utc_now()
    embedding_started = time.perf_counter()
    try:
        query_vector, prompt_tokens = await asyncio.to_thread(_embed)
        if collector is not None:
            collector.record_embedding(
                step_id=f"{telemetry_prefix}.embed_query",
                label="Embed draft query",
                stage=telemetry_stage,
                prompt_tokens=prompt_tokens,
                latency_ms=_elapsed_ms(embedding_started),
                started_at=embedding_started_at,
                ended_at=_utc_now(),
            )
    except Exception as exc:
        if collector is not None:
            collector.record_embedding(
                step_id=f"{telemetry_prefix}.embed_query",
                label="Embed draft query",
                stage=telemetry_stage,
                prompt_tokens=0,
                latency_ms=_elapsed_ms(embedding_started),
                started_at=embedding_started_at,
                ended_at=_utc_now(),
                status="error",
                error=str(exc),
            )
        raise

    def _fetch_neighbors() -> list[dict[str, Any]]:
        conn = resolved_connection_factory(settings)
        try:
            resolved_vector_registrar(conn)
            return resolved_similarity_finder(
                conn,
                query_vector,
                limit=resolved_neighbor_limit,
                user_id=user_id,
                prefer_niche=prefer_niche,
                prefer_age_hours=prefer_age_hours,
            )
        finally:
            conn.close()

    ordinary_rows = await run_timed_thread(
        collector,
        step_id=f"{telemetry_prefix}.vector_search",
        label="Vector similarity search",
        stage=telemetry_stage,
        call_type="db",
        fn=_fetch_neighbors,
    )
    context = RetrievalContext(
        query_embedding=[float(item) for item in query_vector.tolist()],
        embedding_model_version=EMBEDDING_MODEL_VERSION,
        similar_posts=[SimilarPost(**row) for row in ordinary_rows],
    )
    if not include_global_candidates:
        return context

    def _fetch_global_candidates() -> list[dict[str, Any]]:
        conn = resolved_connection_factory(settings)
        try:
            resolved_vector_registrar(conn)
            return resolved_similarity_finder(
                conn,
                query_vector,
                limit=candidate_limit,
                user_id=None,
                prefer_niche=prefer_niche,
                prefer_age_hours=prefer_age_hours,
            )
        finally:
            conn.close()

    try:
        global_rows = await run_timed_thread(
            collector,
            step_id=f"{telemetry_prefix}.cross_reference_search",
            label="Global cross-reference candidate search",
            stage=telemetry_stage,
            call_type="db",
            fn=_fetch_global_candidates,
        )
        context.global_candidates = [SimilarPost(**row) for row in global_rows]
    except Exception as exc:
        context.global_candidate_error = str(exc)

    return context
