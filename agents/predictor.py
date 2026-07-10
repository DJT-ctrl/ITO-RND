"""Predictor Agent for Phase 3 (T3.2).

The predictor is the first point where the Evaluation Cycle becomes more than
similarity search: it uses the 10 nearest historical posts as comparative
context and returns a strict structured prediction for the draft post.

Reach-normalized scoring (T6 Point 1): a deterministic neighbor-weighted score
(processors/benchmark.py::compute_neighbor_prediction) drives the numeric
prediction; the LLM explains that score rather than inventing a percentile.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from agents.schemas import EvaluationDeps, build_voice_profile_section
from config.settings import pydantic_ai_gemini_model


class PredictorOutput(BaseModel):
    predicted_engagement_percentile: float = Field(
        ...,
        ge=0,
        le=100,
        description="Predicted engagement percentile for the draft post, from 0 to 100.",
    )
    predicted_total_engagement: int = Field(
        ...,
        ge=0,
        description="Predicted raw total engagement count (likes + comments + shares).",
    )
    reasoning: str = Field(
        ...,
        min_length=1,
        description="Comparative logic explaining the prediction against similar historical posts.",
    )


def build_predictor_prompt(deps: EvaluationDeps) -> str:
    """Build the Predictor Agent's comparative context prompt."""
    if not deps.similar_posts:
        neighbor_context = (
            "No comparable historical posts were found. Base the prediction on the draft structure only."
        )
    else:
        neighbor_lines = []
        for index, post in enumerate(deps.similar_posts, start=1):
            content = _compact(post.content, limit=500)
            parts = [
                f"Neighbor {index}:",
                f"- Total engagement: {post.total_engagement}",
                f"- Engagement percentile: {post.engagement_percentile:.1f}",
                f"- Likes/comments/shares: {post.likes}/{post.comments}/{post.shares}",
            ]
            if post.follower_count is not None:
                parts.append(f"- Author follower count: {post.follower_count}")
                if post.engagement_rate is not None:
                    parts.append(
                        f"- Engagement rate (engagement/follower): {post.engagement_rate:.4f}"
                    )
                if post.audience_adjusted_percentile is not None:
                    parts.append(
                        f"- Audience-adjusted percentile: {post.audience_adjusted_percentile:.1f}"
                    )
            parts.append(f"- Content: {content}")
            neighbor_lines.append("\n".join(parts))
        neighbor_context = "\n\n".join(neighbor_lines)

    voice_section = build_voice_profile_section(deps.voice_profile)
    deterministic_section = _format_deterministic_score_section(deps.neighbor_prediction)
    draft_author_section = _format_draft_author_section(deps.draft_follower_count)
    reasoning_guidance = _reasoning_guidance(deps.neighbor_prediction)

    return f"""
You are the Predictor Agent for a LinkedIn post evaluation pipeline.

Your task: explain how the draft will perform by comparing it with the nearest
historical posts retrieved from the vector database. The numeric prediction
has already been computed deterministically from those neighbors — your job is
to write clear comparative reasoning, not to invent a different score.
{voice_section}{draft_author_section}{deterministic_section}
Draft post:
{deps.draft_content}

Nearest historical posts:
{neighbor_context}

Reason about:
- How the draft's hook compares with high- and low-performing neighbors.
- Whether its length, specificity, CTA, media implication, and hashtag usage match patterns in the neighbors.
{reasoning_guidance}

Return only structured data matching the required output schema:
- predicted_engagement_percentile: use exactly {deps.neighbor_prediction.get("percentile", 50.0) if deps.neighbor_prediction else "the deterministic score above"}.
- predicted_total_engagement: use exactly {deps.neighbor_prediction.get("total_engagement_estimate", 0) if deps.neighbor_prediction else "the deterministic estimate above"}.
- reasoning: concise comparative explanation grounded in the retrieved neighbors and the deterministic score.
""".strip()


def apply_deterministic_prediction(
    output: PredictorOutput,
    neighbor_prediction: Optional[dict[str, Any]],
) -> PredictorOutput:
    """Force numeric fields to the deterministic neighbor-weighted score."""
    if not neighbor_prediction:
        return output
    return PredictorOutput(
        predicted_engagement_percentile=float(neighbor_prediction["percentile"]),
        predicted_total_engagement=int(neighbor_prediction["total_engagement_estimate"]),
        reasoning=output.reasoning,
    )


def build_predictor_agent(model: Any = None) -> Agent[EvaluationDeps, PredictorOutput]:
    """Create the T3.2 Predictor Agent."""
    resolved_model = pydantic_ai_gemini_model() if model is None else model
    agent: Agent[EvaluationDeps, PredictorOutput] = Agent(
        resolved_model,
        deps_type=EvaluationDeps,
        output_type=PredictorOutput,
    )

    @agent.system_prompt
    def predictor_system_prompt(ctx: RunContext[EvaluationDeps]) -> str:
        return build_predictor_prompt(ctx.deps)

    return agent


def _format_deterministic_score_section(neighbor_prediction: Optional[dict[str, Any]]) -> str:
    if not neighbor_prediction or neighbor_prediction.get("neighbor_count", 0) == 0:
        return ""
    method = neighbor_prediction.get("method", "raw_fallback")
    coverage = neighbor_prediction.get("coverage", 0)
    neighbor_count = neighbor_prediction.get("neighbor_count", 0)
    method_label = (
        "audience-adjusted (reach-normalized)"
        if method == "audience_adjusted"
        else "raw engagement (fallback — insufficient follower data in neighbors)"
    )
    return f"""
Deterministic prediction (computed from neighbors — do not override):
- Predicted percentile: {neighbor_prediction["percentile"]:.1f}
- Predicted total engagement: {neighbor_prediction["total_engagement_estimate"]}
- Scoring method: {method_label}
- Follower-normalized neighbor coverage: {coverage}/{neighbor_count}
"""


def _format_draft_author_section(draft_follower_count: Optional[int]) -> str:
    if draft_follower_count is None:
        return ""
    return f"""
Draft author reach context:
- This draft author has {draft_follower_count:,} followers.
- Neighbor posts were normalized by their own audience size where follower data exists.
"""


def _reasoning_guidance(neighbor_prediction: Optional[dict[str, Any]]) -> str:
    if neighbor_prediction and neighbor_prediction.get("method") == "audience_adjusted":
        return (
            "- Explain why the audience-adjusted percentile is plausible — prioritize reach-normalized "
            "performance over raw view/like totals.\n"
            "- Call out when a neighbor's raw engagement looks high but audience-adjusted rank is lower "
            "(large following inflated raw totals)."
        )
    if neighbor_prediction and neighbor_prediction.get("coverage", 0) > 0:
        return (
            "- Most neighbors lack follower data — explain the prediction using raw engagement percentiles "
            "but note lower confidence because reach normalization is partial.\n"
            "- Mention audience-adjusted figures wherever they are available."
        )
    return (
        "- Why the raw engagement count and percentile are plausible from this local comparison "
        "(no follower-normalized data available for these neighbors)."
    )


def _compact(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."
