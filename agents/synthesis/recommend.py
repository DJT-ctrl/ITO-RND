"""Deterministic recommendation for synthesis variants (easy to swap later)."""

from __future__ import annotations

from typing import Optional, Sequence

from agents.synthesis.schemas import SynthesisRecommendation, SynthesisVariant

# Soft preference: if critic objections were used and counter is within this
# many percentile points of the top score, prefer counter.
_COUNTER_CLOSE_MARGIN = 5.0


def recommend_synthesis_variant(
    variants: Sequence[SynthesisVariant],
    *,
    critic_objection_used: Optional[str] = None,
) -> SynthesisRecommendation:
    """Pick a recommended agent_id with a short human-readable reason."""
    if not variants:
        raise ValueError("recommend_synthesis_variant requires at least one variant")

    ranked = sorted(
        variants,
        key=lambda v: v.predicted_engagement_percentile,
        reverse=True,
    )
    top = ranked[0]
    counter = next((v for v in variants if v.agent_id == "counter"), None)

    if (
        critic_objection_used
        and counter is not None
        and (top.predicted_engagement_percentile - counter.predicted_engagement_percentile)
        <= _COUNTER_CLOSE_MARGIN
    ):
        return SynthesisRecommendation(
            agent_id="counter",
            reason=(
                f"Strategic Counter is within {_COUNTER_CLOSE_MARGIN:.0f} percentile points of "
                f"the top score ({counter.predicted_engagement_percentile:.0f} vs "
                f"{top.predicted_engagement_percentile:.0f}) and addresses the C-suite objection."
            ),
        )

    return SynthesisRecommendation(
        agent_id=top.agent_id,
        reason=(
            f"{top.variant_name} has the highest predicted engagement percentile "
            f"({top.predicted_engagement_percentile:.0f})."
        ),
    )
