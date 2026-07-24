"""Prompt builders for the combined T7.14–T7.16 synthesis generator."""

from __future__ import annotations

from typing import Optional

from agents.prompt_safety import PROMPT_DATA_PREAMBLE, wrap_untrusted_text
from agents.schemas import build_voice_profile_section

GENERIC_CSUITE_BRIEF = (
    "No prior critic run. Assume a skeptical CTO/CFO who wants quantified ROI, "
    "concrete outcomes, and zero fluff. Pre-empt vague claims and missing proof."
)


def build_synthesis_system_prompt(
    *,
    primary_objection: Optional[str] = None,
    voice_profile: Optional[dict] = None,
) -> str:
    """System instructions for one call that returns three specialist rewrites."""
    objection = (primary_objection or "").strip() or GENERIC_CSUITE_BRIEF
    voice_section = build_voice_profile_section(voice_profile)
    objection_block = wrap_untrusted_text(objection, tag="c_suite_objection")

    return f"""
{PROMPT_DATA_PREAMBLE}

You are the Stage 5 Synthesis Optimisation engine for LinkedIn B2B posts.
Rewrite the draft into exactly THREE specialist variants in one response.
Do not invent engagement scores — scoring happens separately.
{voice_section}
C-suite objection brief (for the counter variant only):
{objection_block}

Produce:
1) maximizer (T7.14 Algorithmic Maximizer)
   - Optimize purely for click-through, reach, and virality.
   - Strong hook, scannable structure, clear CTA, topical signals.
   - agent_id must be "maximizer".

2) counter (T7.15 Strategic Counter-Agent)
   - Rewrite to pre-empt the C-suite objection brief above.
   - Address ROI holes / fluff without becoming a dry whitepaper.
   - agent_id must be "counter".

3) brand_purist (T7.16 Brand Purist Agent)
   - High-prestige, brand-safe rewrite prioritizing reputation over virality.
   - Credible, restrained, professional; avoid hype and gimmicks.
   - Respect the voice profile when present.
   - agent_id must be "brand_purist".

For each variant return optimized_text (full post) and rationale (what changed and why).
Keep each rewrite distinct. Stay on the same topic as the draft.
""".strip()


def build_synthesis_user_message(draft_content: str) -> str:
    """Wrapped draft for the generation call."""
    return (
        "Rewrite this LinkedIn draft into the three specialist variants.\n\n"
        f"{wrap_untrusted_text(draft_content)}"
    )
