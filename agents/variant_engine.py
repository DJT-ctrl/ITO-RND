"""Variant Optimisation Engine for Phase 3 (T3.4).

Erdal's spec: "Program a cleanup prompt summarizing criticism vectors to
output 3 distinctly tuned copy alternatives." Success criteria: "Backend
yields exactly 3 ranked structural iterations alongside recalculated
performance estimations."

This module fills the `finalize` hook on `run_evaluation_cycle()`
(agents/orchestrator.py) — it runs sequentially AFTER the concurrent T3.2/T3.3
stage because it needs their *collected* output (predictor score + reasoning,
diagnostic flaws/improvements) as its input.

Two-step process:
  1. One LLM call ("the cleanup prompt") rewrites the draft into exactly 3
     variants, each carrying rewritten copy + a rationale + a strategy label.
  2. The existing T3.2 Predictor Agent is re-run on each of the 3 variant
     texts (concurrently) via agents.variant_scoring.

Neighbor set used for step 2 (caller-selectable via `reembed_neighbors`):
  - Default (False): reuse the SAME neighbors already fetched in stage 1.
  - Opt-in (True): re-embed each variant's own text and fetch its neighbors.
"""

import asyncio
from typing import Any, Awaitable, Callable, List, Literal, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents.prompt_safety import PROMPT_DATA_PREAMBLE, wrap_untrusted_text
from agents.schemas import EvaluationDeps, PostEvaluationState, build_voice_profile_section
from agents.structured_output import agent_structured_output
from agents.variant_scoring import (
    fallback_scores_from_baseline,
    fetch_neighbors_for_text,
    score_text_with_predictor,
)
from config.settings import Settings, pydantic_ai_gemini_model
from telemetry.collector import RunMetadataCollector
from telemetry.instrument import run_agent_step

VariantStrategy = Literal["dimension", "narrative", "tiered"]

_DIAGNOSTIC_NAMES = ("seo", "clarity", "tone")

_STRATEGY_SPECS = {
    "dimension": {
        "title": "Dimension-focused",
        "instructions": (
            "Produce exactly 3 variants, each rewriting the draft to primarily address ONE "
            "of these diagnostic dimensions: SEO/discoverability, clear messaging, tone/brand "
            "persona. If a dimension's diagnostic output is missing below, produce a general "
            "improvement variant for that slot instead of skipping it."
        ),
    },
    "narrative": {
        "title": "Narrative-angle-focused",
        "instructions": (
            "Produce exactly 3 variants, each using a distinctly different narrative strategy: "
            "(1) a bold, attention-grabbing hook, (2) an educational/informative narrative, "
            "(3) a personal story/anecdote angle. Draw on patterns from the historical "
            "neighbor posts where relevant."
        ),
    },
    "tiered": {
        "title": "Risk-tiered",
        "instructions": (
            "Produce exactly 3 variants at increasing levels of change: (1) a minimal, safe "
            "edit preserving most of the original structure, (2) a moderate restructure, "
            "(3) a bold, substantially rewritten variant."
        ),
    },
}


class VariantDraftItem(BaseModel):
    variant_text: str = Field(..., min_length=1, description="The rewritten post copy.")
    rationale: str = Field(
        ..., min_length=1, description="What changed and why it should perform better."
    )
    strategy_label: str = Field(
        ...,
        min_length=1,
        description="Short tag for what this variant targeted, e.g. 'seo-focused', 'bold-rewrite'.",
    )


class VariantDraftSet(BaseModel):
    variants: List[VariantDraftItem] = Field(..., min_length=3, max_length=3)


class VariantOutput(BaseModel):
    variant_text: str
    rationale: str
    strategy_label: str
    predicted_engagement_percentile: float
    predicted_total_engagement: int


def _compact(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def _build_predictor_context(state: PostEvaluationState) -> str:
    if not state.predictor_result:
        return "No predictor output available."
    return (
        f"Predicted engagement percentile: {state.predictor_result.get('predicted_engagement_percentile')}\n"
        f"Predicted total engagement: {state.predictor_result.get('predicted_total_engagement')}\n"
        f"Reasoning: {state.predictor_result.get('reasoning')}"
    )


def _build_diagnostic_context(strategy: VariantStrategy, state: PostEvaluationState) -> str:
    if not state.diagnostics:
        return "No diagnostic output available."

    lines = []
    for name, output in state.diagnostics.items():
        flaws = ", ".join(output.get("flaws", [])) or "none noted"
        improvements = ", ".join(output.get("improvements", [])) or "none noted"
        lines.append(
            f"- {name}: score {output.get('score')}/10; flaws: {flaws}; improvements: {improvements}"
        )
    context = "\n".join(lines)

    if strategy == "dimension":
        missing = [name for name in _DIAGNOSTIC_NAMES if name not in state.diagnostics]
        if missing:
            context += (
                f"\n(Missing diagnostics: {', '.join(missing)} — produce a general-improvement "
                "variant for any slot tied to a missing dimension instead of skipping it.)"
            )
    return context


def _build_neighbor_context(deps: EvaluationDeps) -> str:
    if not deps.similar_posts:
        return "No comparable historical posts were found."
    lines = []
    for index, post in enumerate(deps.similar_posts[:5], start=1):
        content = wrap_untrusted_text(_compact(post.content, limit=300))
        lines.append(
            f"Neighbor {index}: engagement percentile {post.engagement_percentile:.1f} —\n{content}"
        )
    return "\n".join(lines)


def build_variant_prompt(
    strategy: VariantStrategy, deps: EvaluationDeps, state: PostEvaluationState
) -> str:
    """Build the cleanup prompt — the variant engine's sole LLM input."""
    spec = _STRATEGY_SPECS[strategy]
    voice_section = build_voice_profile_section(deps.voice_profile)
    draft_section = wrap_untrusted_text(deps.draft_content)

    return f"""
{PROMPT_DATA_PREAMBLE}

You are the Variant Optimisation Engine in a LinkedIn post evaluation pipeline.

Your task: rewrite the draft post into exactly 3 distinctly tuned alternatives, using the
predicted performance and diagnostic criticism below as your cleanup brief.

Strategy: {spec['title']}
{spec['instructions']}
{voice_section}
Draft post:
{draft_section}

Predictor assessment:
{_build_predictor_context(state)}

Diagnostic criticism:
{_build_diagnostic_context(strategy, state)}

Nearest historical posts (context on what performs well):
{_build_neighbor_context(deps)}

Return only structured data matching the required output schema: exactly 3 variants, each with:
- variant_text: the full rewritten post copy.
- rationale: a concise explanation of what changed and why it should perform better.
- strategy_label: a short tag describing what this variant targeted (e.g. "seo-focused", "bold-rewrite").
""".strip()


def build_variant_generation_agent(model: Any = None) -> Agent[EvaluationDeps, VariantDraftSet]:
    """Create the variant-generation agent."""
    resolved = pydantic_ai_gemini_model() if model is None else model
    return Agent(
        resolved,
        deps_type=EvaluationDeps,
        output_type=agent_structured_output(VariantDraftSet, resolved),
        retries=2,
    )


def _fallback_scores(state: PostEvaluationState) -> tuple[float, int]:
    if state.predictor_result:
        return fallback_scores_from_baseline(
            state.predictor_result.get("predicted_engagement_percentile"),
            state.predictor_result.get("predicted_total_engagement"),
        )
    return fallback_scores_from_baseline()


async def _score_variant(
    item: VariantDraftItem,
    state: PostEvaluationState,
    predictor_agent: Agent,
    reembed_neighbors: bool,
    settings: Optional[Settings],
    collector: Optional[RunMetadataCollector] = None,
) -> Any:
    """Score one variant with the T3.2 predictor agent."""
    if reembed_neighbors:
        neighbors = await fetch_neighbors_for_text(
            item.variant_text,
            settings,  # type: ignore[arg-type]
            collector=collector,
            label=item.strategy_label,
            stage="variant",
        )
    else:
        neighbors = state.similar_posts
    return await score_text_with_predictor(
        item.variant_text,
        predictor_agent=predictor_agent,
        similar_posts=neighbors,
        voice_profile=state.voice_profile,
        collector=collector,
        step_id=f"variant.score.{item.strategy_label.replace(' ', '_').lower()[:32]}",
        label=f"Score variant ({item.strategy_label})",
        stage="variant",
    )


def build_variant_engine(
    predictor_agent: Agent,
    model: Any = None,
    strategy: VariantStrategy = "dimension",
    reembed_neighbors: bool = False,
    settings: Optional[Settings] = None,
    collector: Optional[RunMetadataCollector] = None,
) -> Callable[[PostEvaluationState], Awaitable[None]]:
    """Build the T3.4 finalize hook for run_evaluation_cycle()."""
    if reembed_neighbors and settings is None:
        raise ValueError("build_variant_engine: settings is required when reembed_neighbors=True")

    generation_agent = build_variant_generation_agent(model)

    async def _finalize(state: PostEvaluationState) -> None:
        if state.predictor_result is None and not state.diagnostics:
            state.errors.append(
                "variant_engine: skipped, no predictor or diagnostic output available"
            )
            return

        deps = EvaluationDeps(
            draft_content=state.draft_content,
            similar_posts=state.similar_posts,
            voice_profile=state.voice_profile,
        )
        prompt = build_variant_prompt(strategy, deps, state)

        try:
            gen_result = await run_agent_step(
                collector,
                step_id="variant.generation",
                label="Generate variants",
                stage="variant",
                agent=generation_agent,
                prompt=prompt,
                deps=deps,
                model=pydantic_ai_gemini_model() if model is None else str(model),
            )
        except Exception as exc:
            state.errors.append(f"variant_engine: generation failed: {exc}")
            return

        draft_items = gen_result.output.variants

        rerun_results = await asyncio.gather(
            *(
                _score_variant(
                    item, state, predictor_agent, reembed_neighbors, settings, collector
                )
                for item in draft_items
            ),
            return_exceptions=True,
        )

        fallback_percentile, fallback_engagement = _fallback_scores(state)

        variants: List[VariantOutput] = []
        for item, result in zip(draft_items, rerun_results):
            if isinstance(result, Exception):
                state.errors.append(
                    f"variant_engine: predictor re-run failed for '{item.strategy_label}': {result}"
                )
                percentile, engagement = fallback_percentile, fallback_engagement
            else:
                percentile = result.output.predicted_engagement_percentile
                engagement = result.output.predicted_total_engagement

            variants.append(
                VariantOutput(
                    variant_text=item.variant_text,
                    rationale=item.rationale,
                    strategy_label=item.strategy_label,
                    predicted_engagement_percentile=percentile,
                    predicted_total_engagement=engagement,
                )
            )

        variants.sort(key=lambda v: v.predicted_engagement_percentile, reverse=True)
        state.variants = [v.model_dump() for v in variants]

    return _finalize
