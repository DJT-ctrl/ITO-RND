"""Orchestrate T7.14–T7.16 synthesis: generate → score → recommend."""

from __future__ import annotations

from typing import Any, Optional, Sequence

from pydantic_ai import Agent

from agents.cross_reference import (
    CrossReferencePolicy,
    select_cross_references,
    unavailable_cross_references,
)
from agents.predictor import build_predictor_agent
from agents.retrieval import retrieve_post_context
from agents.synthesis.generator import generate_synthesis_drafts
from agents.synthesis.recommend import recommend_synthesis_variant
from agents.synthesis.schemas import SynthesisDraftItem, SynthesisResult
from agents.synthesis.scoring import score_synthesis_drafts
from api.schemas import CrossReferenceResult, SimilarPost
from config.settings import Settings, pydantic_ai_gemini_model
from processors.benchmark import compute_neighbor_prediction
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
    cross_references: Optional[CrossReferenceResult] = None,
    user_id: Optional[str] = None,
    predictor_agent: Agent | None = None,
    model: Any = None,
    collector: Optional[RunMetadataCollector] = None,
) -> SynthesisResult:
    """Independent Stage 5 optimisation — does not mutate evaluate-loop state.

    ``similar_posts`` is an optional ordinary-scoring shortcut. It is never
    repurposed as cross-reference evidence: callers using it must also pass a
    result selected from a global candidate pool, or synthesis suppresses
    comparison advice rather than inferring it from scoped neighbors.
    """
    errors: list[str] = []
    cleaned = (content or "").strip()
    if not cleaned:
        raise ValueError("run_synthesis: content must be non-empty")

    resolved_model = pydantic_ai_gemini_model() if model is None else model
    predictor = predictor_agent or build_predictor_agent(resolved_model)

    neighbors: list[SimilarPost]
    resolved_cross_references = cross_references
    if similar_posts is not None:
        neighbors = list(similar_posts)
        if settings.cross_reference_enabled and resolved_cross_references is None:
            baseline = compute_neighbor_prediction(neighbors)
            if baseline_percentile is not None:
                baseline = dict(baseline)
                baseline["percentile"] = float(baseline_percentile)
            resolved_cross_references = unavailable_cross_references(
                baseline,
                "Cross-reference advice was skipped because caller-supplied neighbors are not "
                "a verified global candidate pool.",
            )
            errors.append(
                "synthesis: cross-reference advice skipped because only caller-supplied "
                "ordinary neighbors were available"
            )
    else:
        try:
            retrieval_context = await retrieve_post_context(
                cleaned,
                settings,
                collector=collector,
                user_id=user_id,
                global_candidate_limit=settings.cross_reference_candidate_limit,
                telemetry_prefix="synthesis",
                telemetry_stage="variant",
            )
            neighbors = retrieval_context.similar_posts
            if settings.cross_reference_enabled:
                baseline = compute_neighbor_prediction(neighbors)
                if baseline_percentile is not None:
                    baseline = dict(baseline)
                    baseline["percentile"] = float(baseline_percentile)
                if retrieval_context.global_candidate_error:
                    resolved_cross_references = unavailable_cross_references(
                        baseline,
                        "Global cross-reference candidate retrieval failed during synthesis.",
                    )
                    errors.append(
                        "synthesis: global cross-reference candidate retrieval failed: "
                        f"{retrieval_context.global_candidate_error}"
                    )
                else:
                    resolved_cross_references = select_cross_references(
                        retrieval_context.global_candidates,
                        baseline,
                        policy=CrossReferencePolicy(
                            max_references=settings.cross_reference_max_references,
                            min_percentile_uplift=settings.cross_reference_min_percentile_uplift,
                            max_cosine_distance=settings.cross_reference_max_cosine_distance,
                        ),
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
            cross_references=resolved_cross_references,
            model=resolved_model,
        )
    except Exception as exc:
        raise ValueError(f"synthesis generation failed: {exc}") from exc

    scored, score_errors = await score_synthesis_drafts(
        _ordered_drafts(draft_set),
        predictor_agent=predictor,
        similar_posts=neighbors,
        cross_references=resolved_cross_references,
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
