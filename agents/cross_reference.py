"""Deterministic selection of stronger, semantically close historical posts.

This module deliberately selects evidence without an LLM. A later reporting
agent may explain only the references returned here; it must not choose a
new set of posts or turn correlation into a causal claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from agents.prompt_safety import wrap_untrusted_text
from agents.schemas import EvaluationDeps, PostEvaluationState
from agents.structured_output import agent_structured_output
from api.schemas import CrossReferencePost, CrossReferenceResult, SimilarPost
from config.settings import pydantic_ai_gemini_model
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from validation_pipeline.age_buckets import bucket_for_hours

DEFAULT_MAX_REFERENCES = 3
DEFAULT_MIN_PERCENTILE_UPLIFT = 10.0
DEFAULT_MAX_COSINE_DISTANCE = 0.25
_MIN_WORD_COUNT = 10


@dataclass(frozen=True)
class CrossReferencePolicy:
    """Tunable, deterministic selection thresholds for curated evidence."""

    max_references: int = DEFAULT_MAX_REFERENCES
    min_percentile_uplift: float = DEFAULT_MIN_PERCENTILE_UPLIFT
    max_cosine_distance: float = DEFAULT_MAX_COSINE_DISTANCE


class CrossReferenceAnalysisItem(BaseModel):
    """Observations for one already-selected evidence post."""

    post_id: str
    observed_strengths: list[str] = Field(default_factory=list, max_length=3)
    suggested_adaptation: str = Field(..., min_length=1)


class CrossReferenceAnalysisOutput(BaseModel):
    """Structured analyst output constrained to deterministic reference IDs."""

    references: list[CrossReferenceAnalysisItem] = Field(default_factory=list, max_length=3)
    overall_feedback: list[str] = Field(default_factory=list, max_length=3)


def effective_percentile(post: SimilarPost) -> tuple[str, float]:
    """Return the fairer available performance metric for one historical post."""
    if post.audience_adjusted_percentile is not None:
        return "audience_adjusted_percentile", float(post.audience_adjusted_percentile)
    return "engagement_percentile", float(post.engagement_percentile)


def select_cross_references(
    candidates: Sequence[SimilarPost],
    neighbor_prediction: Optional[dict],
    *,
    policy: CrossReferencePolicy = CrossReferencePolicy(),
    prefer_niche: Optional[str] = None,
    prefer_age_hours: Optional[float] = None,
) -> CrossReferenceResult:
    """Select stronger global comparators from already-retrieved candidates.

    Candidates must be semantically close, non-anomalous, and materially above
    the draft's deterministic neighbor baseline. Niche and engagement age only
    act as small tie-breaking preferences so thin slices never hide evidence.
    """
    baseline = float((neighbor_prediction or {}).get("percentile", 50.0))
    baseline_method = (neighbor_prediction or {}).get("method")
    eligible: list[CrossReferencePost] = []

    for post in candidates:
        if not _is_eligible_content(post):
            continue
        if post.engagement_anomaly_flag:
            continue

        distance = float(post.cosine_distance)
        if distance > policy.max_cosine_distance:
            continue

        metric, percentile = effective_percentile(post)
        uplift = percentile - baseline
        if uplift < policy.min_percentile_uplift:
            continue

        semantic_strength = max(
            0.0,
            100.0 * (1.0 - distance / policy.max_cosine_distance),
        )
        score = 0.60 * uplift + 0.40 * semantic_strength
        reasons = [
            (
                f"Semantic match is within the {policy.max_cosine_distance:.2f} "
                f"distance threshold ({distance:.3f})."
            ),
            (
                f"Its {metric.replace('_', ' ')} is {percentile:.1f}, "
                f"{uplift:.1f} points above the draft baseline."
            ),
        ]
        if prefer_niche and post.niche == prefer_niche:
            score += 2.0
            reasons.append(f"Matches the requested niche ({prefer_niche}).")
        if _matches_age_bucket(post, prefer_age_hours):
            score += 1.0
            reasons.append("Matches the requested engagement-age bucket.")

        eligible.append(
            CrossReferencePost(
                post=post,
                comparison_metric=metric,
                effective_percentile=round(percentile, 2),
                percentile_uplift=round(uplift, 2),
                selection_score=round(score, 2),
                selection_reasons=reasons,
            )
        )

    eligible.sort(
        key=lambda item: (
            -item.selection_score,
            item.post.cosine_distance,
            -item.effective_percentile,
            item.post.post_id,
        )
    )
    references = eligible[: policy.max_references]
    if not references:
        return CrossReferenceResult(
            status="insufficient_evidence",
            baseline_percentile=baseline,
            baseline_method=baseline_method,
            candidates_evaluated=len(candidates),
            eligible_candidates=0,
            caveats=[
                "No sufficiently close historical posts materially outperformed this draft's predicted baseline.",
                "No generic substitute advice is shown when the corpus lacks direct comparable evidence.",
            ],
        )

    return CrossReferenceResult(
        status="ready",
        baseline_percentile=baseline,
        baseline_method=baseline_method,
        candidates_evaluated=len(candidates),
        eligible_candidates=len(eligible),
        references=references,
        caveats=[
            "Historical performance is observational; these examples do not prove that a wording choice caused engagement.",
            "Use the structural lessons without copying source wording or assuming identical audience conditions.",
        ],
    )


def unavailable_cross_references(
    neighbor_prediction: Optional[dict],
    reason: str,
) -> CrossReferenceResult:
    """Return a non-fatal result when global candidate retrieval is unavailable."""
    return CrossReferenceResult(
        status="analysis_unavailable",
        baseline_percentile=float((neighbor_prediction or {}).get("percentile", 50.0)),
        baseline_method=(neighbor_prediction or {}).get("method"),
        caveats=[reason],
    )


def mark_analysis_unavailable(
    result: CrossReferenceResult,
    reason: str,
) -> CrossReferenceResult:
    """Keep deterministic evidence when the optional explanatory agent fails."""
    return result.model_copy(
        update={
            "status": "analysis_unavailable",
            "caveats": [*result.caveats, reason],
        }
    )


def apply_cross_reference_analysis(
    result: CrossReferenceResult,
    analysis: CrossReferenceAnalysisOutput,
) -> CrossReferenceResult:
    """Merge analyst observations only for selected IDs, ignoring model drift."""
    seen_ids: set[str] = set()
    updated: list[CrossReferencePost] = []
    for reference in result.references:
        matching = next(
            (
                item
                for item in analysis.references
                if item.post_id == reference.post.post_id and item.post_id not in seen_ids
            ),
            None,
        )
        if matching is not None:
            seen_ids.add(matching.post_id)
            updated.append(
                reference.model_copy(
                    update={
                        "observed_strengths": matching.observed_strengths,
                        "suggested_adaptation": matching.suggested_adaptation,
                    }
                )
            )
        else:
            updated.append(reference)
    return result.model_copy(
        update={
            "references": updated,
            "overall_feedback": analysis.overall_feedback,
        }
    )


def build_cross_reference_analysis_prompt(
    deps: EvaluationDeps,
    state: PostEvaluationState,
) -> str:
    """Build a prompt that can explain evidence but cannot select it."""
    evidence = format_cross_reference_context(
        deps.cross_references,
        include_analysis=False,
    )
    diagnostic_lines = []
    for name, output in state.diagnostics.items():
        improvements = ", ".join(output.get("improvements", [])[:3]) or "none recorded"
        diagnostic_lines.append(f"- {name}: {improvements}")
    diagnostic_context = "\n".join(diagnostic_lines) or "- No diagnostics were available."
    predictor_context = state.predictor_result or {}

    return f"""
You are the Cross-Reference Analyst in a LinkedIn post evaluation pipeline.

Your role is to explain only the deterministically selected historical posts below.
Do not select, add, remove, or rename references. Every `post_id` in your output
must exactly match one selected reference. Describe visible wording or structural
differences only; historical engagement is correlational, not causal. Never copy
source wording into the suggested adaptation.

Draft post:
{wrap_untrusted_text(deps.draft_content)}

Selected evidence:
{evidence}

Predictor assessment:
- Predicted percentile: {predictor_context.get('predicted_engagement_percentile', 'unavailable')}
- Reasoning: {predictor_context.get('reasoning', 'unavailable')}

Diagnostic improvements:
{diagnostic_context}

Return only structured data:
- references: one optional item per selected post_id, each with up to three observable strengths
  and one concise adaptation for this draft.
- overall_feedback: up to three concise, evidence-grounded themes.
""".strip()


def build_cross_reference_analyst(
    model: Any = None,
) -> Agent[EvaluationDeps, CrossReferenceAnalysisOutput]:
    """Create the explanatory agent; deterministic code remains the selector."""
    resolved_model = pydantic_ai_gemini_model() if model is None else model
    return Agent(
        resolved_model,
        deps_type=EvaluationDeps,
        output_type=agent_structured_output(CrossReferenceAnalysisOutput, resolved_model),
        retries=2,
    )


def format_cross_reference_context(
    result: Optional[CrossReferenceResult],
    *,
    include_analysis: bool = True,
) -> str:
    """Render bounded, prompt-safe cross-reference evidence for agents."""
    if result is None:
        return ""
    if result.status == "insufficient_evidence" or not result.references:
        caveats = "\n".join(f"- {item}" for item in result.caveats)
        return f"""
Curated stronger close matches:
- Evidence status: {result.status}.
{caveats}
Do not invent stronger-post comparisons when this evidence is unavailable.
"""

    lines = [
        "Curated stronger close matches (observational evidence, not causal proof):",
        (
            f"- Draft baseline: {result.baseline_percentile:.1f} percentile "
            f"({result.baseline_method or 'neighbor-weighted'})."
        ),
    ]
    for index, reference in enumerate(result.references, start=1):
        post = reference.post
        lines.extend(
            [
                f"Reference {index}: {reference.comparison_metric.replace('_', ' ')} "
                f"{reference.effective_percentile:.1f} "
                f"({reference.percentile_uplift:+.1f} vs baseline).",
                "- Selection: " + " ".join(reference.selection_reasons),
                "- Excerpt:\n" + wrap_untrusted_text(_compact(post.content, 400), tag="cross_reference_post"),
            ]
        )
        if include_analysis and result.status == "ready" and reference.observed_strengths:
            lines.append("- Observed strengths: " + "; ".join(reference.observed_strengths))
        if include_analysis and result.status == "ready" and reference.suggested_adaptation:
            lines.append("- Suggested adaptation: " + reference.suggested_adaptation)
    if include_analysis and result.status == "ready" and result.overall_feedback:
        lines.append("Overall cross-reference feedback:")
        lines.extend(f"- {item}" for item in result.overall_feedback)
    if result.status == "analysis_unavailable":
        lines.append("- Explanatory analysis was unavailable; retain only the deterministic selection facts.")
    lines.append(
        "Use these as structural inspiration only. Do not copy wording or claim a choice caused engagement."
    )
    return "\n".join(lines)


def _is_eligible_content(post: SimilarPost) -> bool:
    if not post.content or not post.content.strip():
        return False
    word_count = post.word_count if post.word_count is not None else len(post.content.split())
    return word_count >= _MIN_WORD_COUNT


def _matches_age_bucket(post: SimilarPost, prefer_age_hours: Optional[float]) -> bool:
    if prefer_age_hours is None or post.engagement_age_hours is None:
        return False
    return bucket_for_hours(float(post.engagement_age_hours)) == bucket_for_hours(
        float(prefer_age_hours)
    )


def _compact(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."
