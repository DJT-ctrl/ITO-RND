"""Shared predictor re-scoring helpers for variants and synthesis.

Used by the T3.4 variant engine finalize hook and the T7.14–T7.16 synthesis
side-step so both paths recalculate performance with the real Predictor
instead of letting a rewrite LLM invent scores.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Tuple

from pgvector.psycopg import register_vector
from pydantic_ai import Agent

from agents.prompt_safety import build_evaluation_user_message
from agents.schemas import EvaluationDeps
from api.schemas import SimilarPost
from config.settings import Settings, pydantic_ai_gemini_model
from processors.embedder import embed_query
from storage.vector_store import find_similar, get_connection
from telemetry.collector import RunMetadataCollector
from telemetry.instrument import run_agent_step, run_timed_thread


def fallback_scores_from_baseline(
    baseline_percentile: Optional[float] = None,
    baseline_total_engagement: Optional[int] = None,
) -> Tuple[float, int]:
    """Best-effort fallback when a predictor re-run fails."""
    return (
        float(baseline_percentile if baseline_percentile is not None else 0.0),
        int(baseline_total_engagement if baseline_total_engagement is not None else 0),
    )


async def fetch_neighbors_for_text(
    text: str,
    settings: Settings,
    *,
    collector: Optional[RunMetadataCollector] = None,
    label: str = "text",
    limit: int = 10,
    user_id: Optional[str] = None,
    stage: str = "variant",
) -> List[SimilarPost]:
    """Embed text and fetch nearest historical neighbors (own DB connection)."""
    safe_label = label.replace(" ", "_").lower()[:32]

    def _embed() -> Tuple[Any, int]:
        return embed_query(text, settings)

    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    try:
        query_vector, prompt_tokens = await asyncio.to_thread(_embed)
        if collector is not None:
            collector.record_embedding(
                step_id=f"{stage}.embed.{safe_label}",
                label=f"Embed ({label})",
                stage=stage,
                prompt_tokens=prompt_tokens,
                latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
            )
    except Exception as exc:
        if collector is not None:
            collector.record_embedding(
                step_id=f"{stage}.embed.{safe_label}",
                label=f"Embed ({label})",
                stage=stage,
                prompt_tokens=0,
                latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
                status="error",
                error=str(exc),
            )
        raise

    def _fetch() -> List[dict]:
        conn = get_connection(settings)
        try:
            register_vector(conn)
            return find_similar(conn, query_vector, limit=limit, user_id=user_id)
        finally:
            conn.close()

    rows = await run_timed_thread(
        collector,
        step_id=f"{stage}.vector_search.{safe_label}",
        label=f"Vector search ({label})",
        stage=stage,
        call_type="db",
        fn=_fetch,
    )
    return [SimilarPost(**row) for row in rows]


async def score_text_with_predictor(
    text: str,
    *,
    predictor_agent: Agent,
    similar_posts: Sequence[SimilarPost],
    voice_profile: Optional[dict] = None,
    collector: Optional[RunMetadataCollector] = None,
    step_id: str = "score.text",
    label: str = "Score text",
    stage: str = "variant",
) -> Any:
    """Run the T3.2 predictor against `text` with the given neighbor set."""
    deps = EvaluationDeps(
        draft_content=text,
        similar_posts=list(similar_posts),
        voice_profile=voice_profile,
    )
    return await run_agent_step(
        collector,
        step_id=step_id,
        label=label,
        stage=stage,
        agent=predictor_agent,
        prompt=build_evaluation_user_message(text),
        deps=deps,
        model=pydantic_ai_gemini_model(),
    )


async def score_texts_concurrently(
    texts: Sequence[tuple[str, str]],
    *,
    predictor_agent: Agent,
    similar_posts: Sequence[SimilarPost],
    voice_profile: Optional[dict] = None,
    collector: Optional[RunMetadataCollector] = None,
    stage: str = "variant",
) -> list[Any]:
    """Score (label, text) pairs concurrently; returns raw gather results."""

    async def _one(label: str, text: str) -> Any:
        safe = label.replace(" ", "_").lower()[:32]
        return await score_text_with_predictor(
            text,
            predictor_agent=predictor_agent,
            similar_posts=similar_posts,
            voice_profile=voice_profile,
            collector=collector,
            step_id=f"{stage}.score.{safe}",
            label=f"Score ({label})",
            stage=stage,
        )

    return await asyncio.gather(
        *(_one(label, text) for label, text in texts),
        return_exceptions=True,
    )
