"""Orchestrate T7.14–T7.16 synthesis: generate → score → recommend."""

from __future__ import annotations

from typing import Any, Optional, Sequence

from pydantic_ai import Agent

from agents.predictor import build_predictor_agent
from agents.synthesis.generator import generate_synthesis_drafts
from agents.synthesis.recommend import recommend_synthesis_variant
from agents.synthesis.schemas import SynthesisDraftItem, SynthesisResult
from agents.synthesis.scoring import score_synthesis_drafts
from agents.variant_scoring import fetch_neighbors_for_text
from api.schemas import SimilarPost
from config.settings import Settings, pydantic_ai_gemini_model
from telemetry.collector import RunMetadataCollector


def _ordered_drafts(draft_set) -> list[SynthesisDraftItem]:
    return [draft_set.maximizer, draft_set.counter, draft_set.brand_purist]


async def run_synthesis(
    content: str,
    settings: Settings,
    *,
    primary_objection: Optional[str] = None,
    baseline_percentile: Optional[float] = None,
    baseline_total_engagement: Optional[int] = None,
    voice_profile: Optional[dict] = None,
    similar_posts: Optional[Sequence[SimilarPost]] = None,
    user_id: Optional[str] = None,
    predictor_agent: Agent | None = None,
    model: Any = None,
    collector: Optional[RunMetadataCollector] = None,
) -> SynthesisResult:
    """Independent Stage 5 optimisation — does not mutate evaluate-loop state."""
    errors: list[str] = []
    cleaned = (content or "").strip()
    if not cleaned:
        raise ValueError("run_synthesis: content must be non-empty")

    resolved_model = pydantic_ai_gemini_model() if model is None else model
    predictor = predictor_agent or build_predictor_agent(resolved_model)

    neighbors: list[SimilarPost]
    if similar_posts is not None:
        neighbors = list(similar_posts)
    else:
        try:
            neighbors = await fetch_neighbors_for_text(
                cleaned,
                settings,
                collector=collector,
                label="synthesis_draft",
                user_id=user_id,
                stage="synthesis",
            )
        except Exception as exc:
            neighbors = []
            errors.append(f"synthesis: neighbor fetch failed: {exc}")

    objection = (primary_objection or "").strip() or None

    try:
        draft_set = await generate_synthesis_drafts(
            cleaned,
            primary_objection=objection,
            voice_profile=voice_profile,
            model=resolved_model,
        )
    except Exception as exc:
        raise ValueError(f"synthesis generation failed: {exc}") from exc

    scored, score_errors = await score_synthesis_drafts(
        _ordered_drafts(draft_set),
        predictor_agent=predictor,
        similar_posts=neighbors,
        voice_profile=voice_profile,
        baseline_percentile=baseline_percentile,
        baseline_total_engagement=baseline_total_engagement,
        collector=collector,
    )
    errors.extend(score_errors)

    # Rank display order by predicted performance (recommendation may still prefer counter).
    scored.sort(key=lambda v: v.predicted_engagement_percentile, reverse=True)
    recommendation = recommend_synthesis_variant(
        scored, critic_objection_used=objection
    )

    return SynthesisResult(
        variants=scored,
        recommendation=recommendation,
        baseline_percentile=baseline_percentile,
        critic_objection_used=objection,
        errors=errors,
    )
