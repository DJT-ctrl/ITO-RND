"""Predictor Agent for Phase 3 (T3.2).

The predictor is the first point where the Evaluation Cycle becomes more than
similarity search: it uses the 10 nearest historical posts as comparative
context and returns a strict structured prediction for the draft post.
"""

from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from agents.schemas import EvaluationDeps, build_voice_profile_section

DEFAULT_MODEL = "google-gla:gemini-2.5-flash"


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
        neighbor_context = "No comparable historical posts were found. Base the prediction on the draft structure only."
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
                parts.extend(
                    [
                        f"- Author follower count: {post.follower_count}",
                        f"- Engagement rate (engagement/follower): {post.engagement_rate:.4f}",
                        f"- Audience-adjusted percentile: {post.audience_adjusted_percentile:.1f}",
                    ]
                )
            parts.append(f"- Content: {content}")
            neighbor_lines.append("\n".join(parts))
        neighbor_context = "\n\n".join(neighbor_lines)

    voice_section = build_voice_profile_section(deps.voice_profile)

    return f"""
You are the Predictor Agent for a LinkedIn post evaluation pipeline.

Your task: predict how the draft will perform by comparing it with the nearest
historical posts retrieved from the vector database.
{voice_section}
Draft post:
{deps.draft_content}

Nearest historical posts:
{neighbor_context}

Reason about:
- How the draft's hook compares with high- and low-performing neighbors.
- Whether its length, specificity, CTA, media implication, and hashtag usage match patterns in the neighbors.
- Why the raw engagement count and percentile are plausible from this local comparison.

Return only structured data matching the required output schema:
- predicted_engagement_percentile: number from 0 to 100.
- predicted_total_engagement: non-negative integer.
- reasoning: concise comparative explanation grounded in the retrieved neighbors.
""".strip()


def build_predictor_agent(model: Any = DEFAULT_MODEL) -> Agent[EvaluationDeps, PredictorOutput]:
    """Create the T3.2 Predictor Agent."""
    agent: Agent[EvaluationDeps, PredictorOutput] = Agent(
        model,
        deps_type=EvaluationDeps,
        output_type=PredictorOutput,
    )

    @agent.system_prompt
    def predictor_system_prompt(ctx: RunContext[EvaluationDeps]) -> str:
        return build_predictor_prompt(ctx.deps)

    return agent


def _compact(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."
