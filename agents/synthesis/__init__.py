"""T7.14–T7.16 synthesis optimisation package (opt-in side-step).

Public surface stays stable for future overhauls (e.g. multi-agent generator).
"""

from agents.synthesis.runner import run_synthesis
from agents.synthesis.schemas import (
    SynthesisAgentId,
    SynthesisRecommendation,
    SynthesisResult,
    SynthesisVariant,
)

__all__ = [
    "SynthesisAgentId",
    "SynthesisRecommendation",
    "SynthesisResult",
    "SynthesisVariant",
    "run_synthesis",
]
