"""Diagnostic Worker Agents for Phase 3 (T3.3).

Each diagnostic worker returns the same JSON shape so the orchestrator can run
all checks concurrently and store their results under stable keys.
"""

from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from agents.discoverability import format_discoverability_context_section
from agents.prompt_safety import PROMPT_DATA_PREAMBLE, wrap_untrusted_text
from agents.schemas import EvaluationDeps, build_voice_profile_section
from config.settings import pydantic_ai_gemini_model


class DiagnosticOutput(BaseModel):
    score: float = Field(
        ...,
        ge=0,
        le=10,
        description="Diagnostic quality score from 0 to 10.",
    )
    flaws: list[str] = Field(
        default_factory=list,
        description="Specific weaknesses or risks found in the draft.",
    )
    advantages: list[str] = Field(
        default_factory=list,
        description="Specific strengths found in the draft.",
    )
    improvements: list[str] = Field(
        default_factory=list,
        description="Concrete changes that would improve this diagnostic dimension.",
    )


_DIAGNOSTIC_SPECS = {
    "seo": {
        "title": "SEO and discoverability",
        "focus": (
            "Evaluate keyword clarity, hashtag usefulness, search/discovery value, "
            "and whether the post gives LinkedIn enough topical signals."
        ),
    },
    "clarity": {
        "title": "Clear messaging",
        "focus": (
            "Evaluate whether the main point is immediately understandable, whether "
            "the structure is easy to scan, and whether the CTA is unambiguous."
        ),
    },
    "tone": {
        "title": "Tone and brand persona",
        "focus": (
            "Evaluate whether the voice feels credible, professional, human, and "
            "consistent with a thoughtful LinkedIn brand persona."
        ),
    },
}


def build_diagnostic_prompt(name: str, deps: EvaluationDeps) -> str:
    """Build one diagnostic worker's prompt."""
    spec = _DIAGNOSTIC_SPECS[name]
    voice_section = build_voice_profile_section(deps.voice_profile)
    draft_section = wrap_untrusted_text(deps.draft_content)
    return f"""
{PROMPT_DATA_PREAMBLE}

You are the {spec['title']} Diagnostic Worker in a LinkedIn post evaluation pipeline.

Your focus:
{spec['focus']}
{voice_section}
Draft post:
{draft_section}

Return only structured data matching the required output schema:
- score: number from 0 to 10.
- flaws: list of specific weaknesses or risks.
- advantages: list of specific strengths.
- improvements: list of concrete edits that would improve this dimension.

Be direct and practical. Do not invent metrics outside this schema.
""".strip()


def build_seo_prompt(deps: EvaluationDeps) -> str:
    """Build the SEO worker prompt — corpus-grounded or legacy baseline."""
    if deps.seo_mode == "gemini_only":
        return build_diagnostic_prompt("seo", deps)

    base = build_diagnostic_prompt("seo", deps)
    context = deps.discoverability_context or {}
    section = format_discoverability_context_section(context)
    if not section:
        return base

    # Stable corpus block first — helps Gemini implicit prefix caching.
    return f"{section}\n\n{base}"


def build_seo_agent(model: Any = None) -> Agent[EvaluationDeps, DiagnosticOutput]:
    return _build_seo_agent(pydantic_ai_gemini_model() if model is None else model)


def build_clarity_agent(model: Any = None) -> Agent[EvaluationDeps, DiagnosticOutput]:
    return _build_diagnostic_agent("clarity", pydantic_ai_gemini_model() if model is None else model)


def build_tone_agent(model: Any = None) -> Agent[EvaluationDeps, DiagnosticOutput]:
    return _build_diagnostic_agent("tone", pydantic_ai_gemini_model() if model is None else model)


def build_diagnostic_agents(model: Any = None) -> dict[str, Agent[EvaluationDeps, DiagnosticOutput]]:
    resolved = pydantic_ai_gemini_model() if model is None else model
    return {
        "seo": build_seo_agent(resolved),
        "clarity": build_clarity_agent(resolved),
        "tone": build_tone_agent(resolved),
    }


def _build_seo_agent(model: Any) -> Agent[EvaluationDeps, DiagnosticOutput]:
    agent: Agent[EvaluationDeps, DiagnosticOutput] = Agent(
        model,
        deps_type=EvaluationDeps,
        output_type=DiagnosticOutput,
    )

    @agent.system_prompt
    def seo_system_prompt(ctx: RunContext[EvaluationDeps]) -> str:
        return build_seo_prompt(ctx.deps)

    return agent


def _build_diagnostic_agent(name: str, model: Any) -> Agent[EvaluationDeps, DiagnosticOutput]:
    agent: Agent[EvaluationDeps, DiagnosticOutput] = Agent(
        model,
        deps_type=EvaluationDeps,
        output_type=DiagnosticOutput,
    )

    @agent.system_prompt
    def diagnostic_system_prompt(ctx: RunContext[EvaluationDeps]) -> str:
        return build_diagnostic_prompt(name, ctx.deps)

    return agent
