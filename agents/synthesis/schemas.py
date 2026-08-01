"""Stable schemas for the T7.14–T7.16 synthesis optimisation side-step."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

SynthesisAgentId = Literal["maximizer", "counter", "brand_purist"]

AGENT_DISPLAY_NAMES: dict[SynthesisAgentId, str] = {
    "maximizer": "Algorithmic Maximizer",
    "counter": "Strategic Counter",
    "brand_purist": "Brand Purist",
}


class SynthesisDraftItem(BaseModel):
    """One rewrite from the generation LLM (pre-scoring)."""

    agent_id: SynthesisAgentId
    optimized_text: str = Field(..., min_length=1)
    rationale: str = Field(..., min_length=1)


class SynthesisDraftSet(BaseModel):
    """Exactly three specialist rewrites from one Gemini call."""

    maximizer: SynthesisDraftItem
    counter: SynthesisDraftItem
    brand_purist: SynthesisDraftItem


class SynthesisVariant(BaseModel):
    """Scored synthesis rewrite (sheet-shaped + performance)."""

    agent_id: SynthesisAgentId
    variant_name: str
    optimized_text: str
    rationale: str
    predicted_engagement_percentile: float
    predicted_total_engagement: int
    delta_percentile: Optional[float] = None


class SynthesisRecommendation(BaseModel):
    agent_id: SynthesisAgentId
    reason: str


class SynthesisResult(BaseModel):
    """Stable API/UI contract for Stage 5 optimisation."""

    variants: list[SynthesisVariant] = Field(..., min_length=3, max_length=3)
    recommendation: SynthesisRecommendation
    baseline_percentile: Optional[float] = None
    critic_objection_used: Optional[str] = None
    errors: list[str] = Field(default_factory=list)
