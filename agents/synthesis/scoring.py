"""Scoring helpers for synthesis variants (wraps shared variant_scoring)."""

from __future__ import annotations

from typing import Optional, Sequence

from pydantic_ai import Agent

from agents.synthesis.schemas import (
    AGENT_DISPLAY_NAMES,
    SynthesisDraftItem,
    SynthesisVariant,
)
from agents.variant_scoring import (
    fallback_scores_from_baseline,
    score_texts_concurrently,
)
from api.schemas import SimilarPost
from telemetry.collector import RunMetadataCollector


async def score_synthesis_drafts(
    drafts: Sequence[SynthesisDraftItem],
    *,
    predictor_agent: Agent,
    similar_posts: Sequence[SimilarPost],
    voice_profile: Optional[dict] = None,
    baseline_percentile: Optional[float] = None,
    baseline_total_engagement: Optional[int] = None,
    collector: Optional[RunMetadataCollector] = None,
) -> tuple[list[SynthesisVariant], list[str]]:
    """Predictor re-score each draft; soft-fail into errors + baseline fallback."""
    errors: list[str] = []
    pairs = [(d.agent_id, d.optimized_text) for d in drafts]
    results = await score_texts_concurrently(
        pairs,
        predictor_agent=predictor_agent,
        similar_posts=similar_posts,
        voice_profile=voice_profile,
        collector=collector,
        stage="synthesis",
    )
    fallback_pct, fallback_eng = fallback_scores_from_baseline(
        baseline_percentile, baseline_total_engagement
    )

    scored: list[SynthesisVariant] = []
    for draft, result in zip(drafts, results):
        if isinstance(result, Exception):
            errors.append(f"synthesis: score failed for {draft.agent_id}: {result}")
            percentile, engagement = fallback_pct, fallback_eng
        else:
            percentile = float(result.output.predicted_engagement_percentile)
            engagement = int(result.output.predicted_total_engagement)

        delta = None
        if baseline_percentile is not None:
            delta = round(percentile - float(baseline_percentile), 1)

        scored.append(
            SynthesisVariant(
                agent_id=draft.agent_id,
                variant_name=AGENT_DISPLAY_NAMES[draft.agent_id],
                optimized_text=draft.optimized_text,
                rationale=draft.rationale,
                predicted_engagement_percentile=percentile,
                predicted_total_engagement=engagement,
                delta_percentile=delta,
            )
        )
    return scored, errors
