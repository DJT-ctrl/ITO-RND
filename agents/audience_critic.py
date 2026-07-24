"""T7.11–T7.13 combined synthetic audience critic (Gemini, independent side-step).

One agent covers three lenses in a single structured response:
  - T7.11 C-Suite / Enterprise — skeptical ROI-focused executive
  - T7.12 End-User / Practitioner — daily operator tactical value
  - T7.13 Industry Peer / Competitor — thought-leadership credibility

Not wired into the evaluate orchestrator loop. Call via POST /api/v1/critique
or the Evaluation Cycle "Run critic" button.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents.prompt_safety import (
    PROMPT_DATA_PREAMBLE,
    build_evaluation_user_message,
    wrap_untrusted_text,
)
from agents.structured_output import agent_structured_output
from config.settings import pydantic_ai_gemini_model


class CSuiteLens(BaseModel):
    """T7.11 — skeptical CTO/CFO lens."""

    reaction: str = Field(..., description="Short gut reaction from an executive.")
    primary_objection: str = Field(
        ...,
        description="The main hole in the value proposition or ROI case.",
    )
    roi_notes: str = Field(
        default="",
        description="ROI / fluff / risk notes an executive would flag.",
    )


class PractitionerLens(BaseModel):
    """T7.12 — daily operator lens."""

    reaction: str = Field(..., description="Short gut reaction from a practitioner.")
    perceived_value: str = Field(
        ...,
        description="Whether the post offers real tactical value for daily work.",
    )
    tactical_gaps: str = Field(
        default="",
        description="Missing steps, tools, or concrete takeaways operators need.",
    )


class PeerLens(BaseModel):
    """T7.13 — industry peer / competitor lens."""

    reaction: str = Field(..., description="Short gut reaction from a peer.")
    credibility_check: str = Field(
        ...,
        description="Thought-leadership credibility assessment within the market.",
    )
    originality_notes: str = Field(
        default="",
        description="Originality vs familiar LinkedIn tropes / competitor noise.",
    )


class AudienceCriticOutput(BaseModel):
    """Combined T7.11 + T7.12 + T7.13 synthetic audience critique."""

    overall_verdict: str = Field(
        ...,
        description="Short skeptical summary across all three lenses.",
    )
    score: float = Field(
        ...,
        ge=0,
        le=10,
        description="Overall persuasiveness / substance score 0–10.",
    )
    c_suite: CSuiteLens
    practitioner: PractitionerLens
    peer: PeerLens


AUDIENCE_CRITIC_SYSTEM_PROMPT = f"""
{PROMPT_DATA_PREAMBLE}

You are an independent synthetic-audience critic for LinkedIn B2B posts.
You are NOT part of the scoring/diagnostics loop — give a fresh, skeptical read.
Do not flatter. Prefer concrete objections over vague praise.

Evaluate the draft through three lenses in one structured response:

1) c_suite (T7.11 — primary): Skeptical CTO/CFO. Hunt for ROI holes, fluff,
   vague claims, and reasons an executive would dismiss or challenge the post.
   Fill reaction, primary_objection, roi_notes.

2) practitioner (T7.12): Daily operator / practitioner. Would this help someone
   do their job tomorrow? Flag actionable value vs empty inspiration.
   Fill reaction, perceived_value, tactical_gaps.

3) peer (T7.13): Industry founder / agency peer / competitor. Assess
   thought-leadership credibility and originality in-market.
   Fill reaction, credibility_check, originality_notes.

Also return:
- overall_verdict: 1–3 sentence skeptical summary across lenses.
- score: 0–10 overall persuasiveness/substance (not engagement prediction).

Be direct and practical. Do not invent facts not implied by the draft.
""".strip()


def build_audience_critic_system_prompt(draft_content: str = "") -> str:
    """System prompt; optional draft inclusion for tests that inspect grounding."""
    if not draft_content:
        return AUDIENCE_CRITIC_SYSTEM_PROMPT
    draft_section = wrap_untrusted_text(draft_content)
    return (
        f"{AUDIENCE_CRITIC_SYSTEM_PROMPT}\n\n"
        f"Draft post (also provided as the user message):\n{draft_section}"
    )


def build_audience_critic_user_message(draft_content: str) -> str:
    """Wrapped user message for agent.run()."""
    return build_evaluation_user_message(draft_content)


def build_audience_critic_agent(
    model: Any = None,
) -> Agent[None, AudienceCriticOutput]:
    """Build the combined synthetic-audience critic agent (Gemini)."""
    resolved = pydantic_ai_gemini_model() if model is None else model
    agent: Agent[None, AudienceCriticOutput] = Agent(
        resolved,
        output_type=agent_structured_output(AudienceCriticOutput, resolved),
        system_prompt=AUDIENCE_CRITIC_SYSTEM_PROMPT,
        retries=2,
    )
    return agent


async def run_audience_critic(
    content: str,
    *,
    agent: Agent[None, AudienceCriticOutput] | None = None,
    model: Any = None,
) -> AudienceCriticOutput:
    """Run the critic on draft text only (no evaluate-loop deps)."""
    critic = agent if agent is not None else build_audience_critic_agent(model)
    result = await critic.run(build_audience_critic_user_message(content))
    return result.output
