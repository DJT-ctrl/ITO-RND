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
     Which 3 axes the variants target is controlled by `strategy` (see
     `VariantStrategy` below) and is caller-selectable, not hardcoded.
  2. The existing T3.2 Predictor Agent is re-run on each of the 3 variant
     texts (concurrently) to get the "recalculated performance estimations"
     from the same scoring method as the rest of the pipeline, rather than
     the generation LLM guessing its own number. Variants are ranked by this
     recalculated score, descending.

Neighbor set used for step 2 (caller-selectable via `reembed_neighbors`):
  - Default (False): reuse the SAME neighbors already fetched in stage 1
    against the original draft (cheap — 0 extra Gemini/DB calls). Fair when
    variants are close rewrites of the original topic, and keeps all 3
    variants scored against one shared baseline for consistent comparison.
  - Opt-in (True): re-embed each variant's own text and fetch ITS OWN
    nearest neighbors before scoring it. More accurate when a variant
    meaningfully shifts topic/angle (e.g. a "narrative" strategy variant
        telling a different story), at the cost of up to 3 extra Gemini embed
        calls + 6 extra DB queries (ordinary scoring neighbors and global
        comparison candidates for each variant).
"""

import asyncio
from typing import Any, Awaitable, Callable, List, Literal, Optional, Tuple

from pgvector.psycopg import register_vector
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents.cross_reference import (
    CrossReferencePolicy,
    format_cross_reference_context,
    select_cross_references,
    unavailable_cross_references,
)
from agents.prompt_safety import PROMPT_DATA_PREAMBLE, wrap_untrusted_text, build_evaluation_user_message
from agents.retrieval import retrieve_post_context
from agents.schemas import EvaluationDeps, PostEvaluationState, build_voice_profile_section, resolve_neighbor_limit
from agents.structured_output import agent_structured_output
from api.schemas import CrossReferenceResult, SimilarPost
from config.settings import Settings, pydantic_ai_gemini_model
from processors.benchmark import compute_neighbor_prediction
from processors.embedder import embed_query
from storage.vector_store import find_similar, get_connection
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
        lines.append(f"- {name}: score {output.get('score')}/10; flaws: {flaws}; improvements: {improvements}")
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


def build_variant_prompt(strategy: VariantStrategy, deps: EvaluationDeps, state: PostEvaluationState) -> str:
    """Build the "cleanup prompt" — the variant engine's sole LLM input.

    Summarizes the predictor's score/reasoning and whatever diagnostic
    criticism exists (T3.3 may not have produced all 3 checks, see
    build_variant_engine's "run with what's available" rule) plus the
    nearest historical posts, then instructs the model per the selected
    strategy (see VariantStrategy).
    """
    spec = _STRATEGY_SPECS[strategy]
    voice_section = build_voice_profile_section(deps.voice_profile)
    cross_reference_section = format_cross_reference_context(deps.cross_references)
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

Curated stronger close matches:
{cross_reference_section}

Nearest historical posts (context on what performs well):
{_build_neighbor_context(deps)}

Return only structured data matching the required output schema: exactly 3 variants, each with:
- variant_text: the full rewritten post copy.
- rationale: a concise explanation of what changed and why it should perform better.
- strategy_label: a short tag describing what this variant targeted (e.g. "seo-focused", "bold-rewrite").
""".strip()


def build_variant_generation_agent(model: Any = None) -> Agent[EvaluationDeps, VariantDraftSet]:
    """Create the variant-generation agent.

    Unlike the T3.2/T3.3 agents, this one has no `@agent.system_prompt`
    hook tied to `ctx.deps` — the full "cleanup prompt" (built by
    build_variant_prompt, which needs predictor_result/diagnostics from
    PostEvaluationState, not just EvaluationDeps) is passed directly as the
    run's user prompt instead.
    """
    resolved = pydantic_ai_gemini_model() if model is None else model
    return Agent(
        resolved,
        deps_type=EvaluationDeps,
        output_type=agent_structured_output(VariantDraftSet, resolved),
        retries=2,
    )


def _fallback_scores(state: PostEvaluationState) -> Tuple[float, int]:
    """Fallback recalculated score if a variant's predictor re-run fails —
    reuse the original draft's predictor score rather than crash/zero it
    out, since it's the best available estimate."""
    if state.predictor_result:
        return (
            float(state.predictor_result.get("predicted_engagement_percentile", 0.0)),
            int(state.predictor_result.get("predicted_total_engagement", 0)),
        )
    return 0.0, 0


async def _fetch_variant_context(
    variant_text: str,
    settings: Settings,
    collector: Optional[RunMetadataCollector] = None,
    strategy_label: str = "variant",
    neighbor_limit: int = 10,
    user_id: Optional[str] = None,
    prefer_niche: Optional[str] = None,
) -> tuple[List[SimilarPost], Optional[CrossReferenceResult]]:
    """Fetch fresh ordinary and global evidence for one re-embedded variant."""
    limit = resolve_neighbor_limit(neighbor_limit)
    safe_label = strategy_label.replace(" ", "_").lower()[:32]
    context = await retrieve_post_context(
        variant_text,
        settings,
        neighbor_limit=limit,
        global_candidate_limit=getattr(settings, "cross_reference_candidate_limit", 30),
        user_id=user_id,
        prefer_niche=prefer_niche,
        include_global_candidates=getattr(settings, "cross_reference_enabled", True),
        collector=collector,
        telemetry_prefix=f"variant.{safe_label}",
        telemetry_stage="variant",
        embedder=embed_query,
        connection_factory=get_connection,
        similarity_finder=find_similar,
        vector_registrar=register_vector,
    )
    if not getattr(settings, "cross_reference_enabled", True):
        return context.similar_posts, None

    neighbor_prediction = compute_neighbor_prediction(context.similar_posts)
    if context.global_candidate_error:
        return context.similar_posts, unavailable_cross_references(
            neighbor_prediction,
            "Global cross-reference candidate retrieval failed for this re-embedded variant.",
        )
    return context.similar_posts, select_cross_references(
        context.global_candidates,
        neighbor_prediction,
        policy=CrossReferencePolicy(
            max_references=getattr(settings, "cross_reference_max_references", 3),
            min_percentile_uplift=getattr(settings, "cross_reference_min_percentile_uplift", 10.0),
            max_cosine_distance=getattr(settings, "cross_reference_max_cosine_distance", 0.25),
        ),
    )


async def _score_variant(
    item: VariantDraftItem,
    state: PostEvaluationState,
    predictor_agent: Agent,
    reembed_neighbors: bool,
    settings: Optional[Settings],
    collector: Optional[RunMetadataCollector] = None,
    neighbor_limit: int = 10,
) -> Any:
    """Score one variant with the T3.2 predictor agent, using either the
    shared stage-1 neighbors or this variant's own re-embedded neighbors
    (see module docstring for the tradeoff)."""
    if reembed_neighbors:
        neighbors, cross_references = await _fetch_variant_context(
            item.variant_text,
            settings,
            collector=collector,
            strategy_label=item.strategy_label,
            neighbor_limit=neighbor_limit,
            user_id=state.retrieval_user_id,
            prefer_niche=state.retrieval_prefer_niche,
        )
    else:
        neighbors = state.similar_posts
        cross_references = state.cross_references
    deps = EvaluationDeps(
        draft_content=item.variant_text,
        similar_posts=neighbors,
        cross_references=cross_references,
        voice_profile=state.voice_profile,
    )
    safe_label = item.strategy_label.replace(" ", "_").lower()[:32]
    return await run_agent_step(
        collector,
        step_id=f"variant.score.{safe_label}",
        label=f"Score variant ({item.strategy_label})",
        stage="variant",
        agent=predictor_agent,
        prompt=build_evaluation_user_message(item.variant_text),
        deps=deps,
        model=pydantic_ai_gemini_model(),
    )


def build_variant_engine(
    predictor_agent: Agent,
    model: Any = None,
    strategy: VariantStrategy = "dimension",
    reembed_neighbors: bool = False,
    settings: Optional[Settings] = None,
    collector: Optional[RunMetadataCollector] = None,
    neighbor_limit: int = 10,
) -> Callable[[PostEvaluationState], Awaitable[None]]:
    """Build the T3.4 finalize hook for run_evaluation_cycle().

    Args:
        predictor_agent: the same T3.2 predictor agent already built for
            the concurrent evaluation stage — reused here to recalculate a
            score for each generated variant (Decision: re-run the real
            predictor rather than have the generation LLM guess a number).
        model: PydanticAI model identifier for the variant-generation call.
        strategy: which distinctness axis to use (see VariantStrategy) —
            caller-selectable (API request field / dashboard control), not
            fixed.
        reembed_neighbors: if True, each variant re-embeds its own text and
            fetches its own nearest neighbors for scoring, instead of
            reusing the shared stage-1 neighbors (see module docstring).
            Requires `settings` to be provided.
        settings: required when reembed_neighbors=True (fails fast at build
            time, before any request runs, if missing).
        neighbor_limit: when reembed_neighbors=True, how many neighbors each
            variant fetches (default 10, max 100 — same as stage 1).
    """
    if reembed_neighbors and settings is None:
        raise ValueError("build_variant_engine: settings is required when reembed_neighbors=True")

    resolved_neighbor_limit = resolve_neighbor_limit(neighbor_limit)
    generation_agent = build_variant_generation_agent(model)

    async def _finalize(state: PostEvaluationState) -> None:
        # Nothing at all to work from — skip entirely rather than ask the
        # model to invent criticism out of thin air.
        if state.predictor_result is None and not state.diagnostics:
            state.errors.append("variant_engine: skipped, no predictor or diagnostic output available")
            return

        deps = EvaluationDeps(
            draft_content=state.draft_content,
            similar_posts=state.similar_posts,
            cross_references=state.cross_references,
            voice_profile=state.voice_profile,
        )
        prompt = build_variant_prompt(strategy, deps, state)

        gen_result = None
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
                    item,
                    state,
                    predictor_agent,
                    reembed_neighbors,
                    settings,
                    collector,
                    neighbor_limit=resolved_neighbor_limit,
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
