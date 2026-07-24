"""One-call Gemini generator for maximizer / counter / brand_purist drafts."""

from __future__ import annotations

from typing import Any, Optional

from pydantic_ai import Agent

from agents.structured_output import agent_structured_output
from agents.synthesis.prompts import (
    build_synthesis_system_prompt,
    build_synthesis_user_message,
)
from agents.synthesis.schemas import SynthesisDraftSet
from config.settings import pydantic_ai_gemini_model


def build_synthesis_generation_agent(model: Any = None) -> Agent[None, SynthesisDraftSet]:
    """Build the combined synthesis rewrite agent (overhaul seam: swap later)."""
    resolved = pydantic_ai_gemini_model() if model is None else model
    return Agent(
        resolved,
        output_type=agent_structured_output(SynthesisDraftSet, resolved),
        system_prompt=build_synthesis_system_prompt(),
        retries=2,
    )


async def generate_synthesis_drafts(
    content: str,
    *,
    primary_objection: Optional[str] = None,
    voice_profile: Optional[dict] = None,
    agent: Agent[None, SynthesisDraftSet] | None = None,
    model: Any = None,
) -> SynthesisDraftSet:
    """Run one Gemini call → three specialist draft rewrites."""
    # Rebuild agent when objection/voice change so the system prompt matches.
    if agent is None or primary_objection is not None or voice_profile is not None:
        resolved = pydantic_ai_gemini_model() if model is None else model
        agent = Agent(
            resolved,
            output_type=agent_structured_output(SynthesisDraftSet, resolved),
            system_prompt=build_synthesis_system_prompt(
                primary_objection=primary_objection,
                voice_profile=voice_profile,
            ),
            retries=2,
        )
    result = await agent.run(build_synthesis_user_message(content))
    drafts = result.output
    # Normalize agent_ids in case the model drifts.
    drafts.maximizer.agent_id = "maximizer"
    drafts.counter.agent_id = "counter"
    drafts.brand_purist.agent_id = "brand_purist"
    return drafts
