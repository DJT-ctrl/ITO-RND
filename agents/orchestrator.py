"""Async state orchestrator for the Phase 3 evaluation cycle (T3.1), built on
PydanticAI.

Erdal's spec: "Build a lightweight state router using PydanticAI or native
Python async primitives to run concurrent evaluations." Success criteria:
"Content execution cycle executes successfully end-to-end without dropping
system data or leaking memory."

Decision: PydanticAI (`pydantic_ai.Agent`), staying on Gemini via the
`google:` provider — PydanticAI reads GEMINI_API_KEY from the
environment automatically (already loaded by config/settings.py's
load_dotenv()), so no extra credential wiring is needed here.

Pipeline shape (NOT one flat concurrent blob):
  1. Sequential setup   — fetch the 10 nearest vector neighbors (reuses T2's
                           embed_query()/find_similar()). T3.2's Predictor
                           Agent needs this as input context, so it must
                           finish before any evaluation agent runs.
  2. Concurrent evaluate — this is T3.1's actual deliverable: run a
                           caller-supplied Predictor agent + any number of
                           named Diagnostic Worker agents at the same time,
                           each a `pydantic_ai.Agent` sharing `EvaluationDeps`
                           (draft content + neighbors) as read-only context.
                           One agent failing must not drop the others'
                           results.
  3. Sequential finalize — optional hook for T3.4's Variant Optimisation
                           Engine, which needs stage 2's *collected* output
                           as input, so it can't run concurrently with it.

No real agent logic (predictor/diagnostic/variant) lives here — that's
T3.2/T3.3/T3.4. This module only proves the PydanticAI + concurrency/state
plumbing, verified in tests with `pydantic_ai.models.test.TestModel` (no
real network calls).
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from pgvector.psycopg import register_vector
from pydantic import BaseModel
from pydantic_ai import Agent

from agents.clarity_metrics import compute_clarity_metrics
from agents.discoverability_context import gather_discoverability_context, resolve_use_google_trends
from agents.predictor import apply_deterministic_prediction
from agents.prompt_safety import build_evaluation_user_message
from agents.schemas import (
    EvaluationDeps,
    PostEvaluationState,
    SeoDiscoverabilityMode,
    resolve_neighbor_limit,
)
from agents.visual_diagnostics import (
    build_visual_agent,
    build_visual_user_prompt,
    prepare_visual_image,
    resolve_use_visual_diagnostics,
)
from config.settings import Settings, pydantic_ai_gemini_model
from processors.benchmark import compute_neighbor_prediction
from processors.embedder import embed_query, EMBEDDING_MODEL_VERSION
from storage.profile_store import get_follower_count
from storage.vector_store import find_similar, get_connection, get_user_voice_profile
from telemetry.collector import RunMetadataCollector
from telemetry.instrument import run_agent_step, run_timed_thread
from telemetry.persist import save_run_metadata


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)

# A PydanticAI agent sharing our EvaluationDeps as read-only context. T3.2's
# Predictor Agent and T3.3's Diagnostic Worker Agents will each be one of
# these, registered into run_evaluation_cycle below.
EvaluationAgent = Agent[EvaluationDeps, Any]

# Plain async hook (not necessarily an LLM call) for the sequential finalize
# stage — future extension point for T3.4.
FinalizeHook = Callable[[PostEvaluationState], Awaitable[None]]


async def _gather_similar_posts(
    state: PostEvaluationState,
    settings: Settings,
    user_id: Optional[str] = None,
    collector: Optional[RunMetadataCollector] = None,
    neighbor_limit: int = 10,
) -> None:
    """Populate state.similar_posts with the nearest vector neighbors.

    `neighbor_limit` defaults to 10 (sheet/T7.1 default) and may be raised
    up to 100 for a wider comparison surface. Validated via
    ``resolve_neighbor_limit``.

    Wraps the existing *synchronous* embed_query() (processors/embedder.py)
    and find_similar()/get_connection() (storage/vector_store.py) via
    asyncio.to_thread — both do blocking I/O (a Gemini HTTP call, a
    blocking psycopg query) and would otherwise stall the event loop during
    the concurrent evaluation stage that follows.

    Opens and closes its own DB connection inside the offloaded call, same
    per-request pattern as api/main.py — nothing is held open across the
    concurrent stage, which is the "no leaking memory" half of Erdal's
    success criterion.

    If `user_id` is given, retrieval is tenant-scoped to that subscriber's
    own posts, with an automatic fallback to the global corpus when they
    don't have enough of their own (see find_similar()'s docstring).
    """
    limit = resolve_neighbor_limit(neighbor_limit)

    def _embed() -> tuple[Any, int]:
        return embed_query(state.draft_content, settings)

    started_at = _utc_now()
    t0 = time.perf_counter()
    try:
        query_vector, prompt_tokens = await asyncio.to_thread(_embed)
        state.query_embedding = [float(x) for x in query_vector.tolist()]
        state.embedding_model_version = EMBEDDING_MODEL_VERSION
        if collector is not None:
            collector.record_embedding(
                step_id="retrieval.embed_query",
                label="Embed draft query",
                stage="retrieval",
                prompt_tokens=prompt_tokens,
                latency_ms=_elapsed_ms(t0),
                started_at=started_at,
                ended_at=_utc_now(),
            )
    except Exception as exc:
        if collector is not None:
            collector.record_embedding(
                step_id="retrieval.embed_query",
                label="Embed draft query",
                stage="retrieval",
                prompt_tokens=0,
                latency_ms=_elapsed_ms(t0),
                started_at=started_at,
                ended_at=_utc_now(),
                status="error",
                error=str(exc),
            )
        raise

    def _fetch() -> list[dict]:
        conn = get_connection(settings)
        try:
            register_vector(conn)
            return find_similar(conn, query_vector, limit=limit, user_id=user_id)
        finally:
            conn.close()

    rows = await run_timed_thread(
        collector,
        step_id="retrieval.vector_search",
        label="Vector similarity search",
        stage="retrieval",
        call_type="db",
        fn=_fetch,
    )
    from api.schemas import SimilarPost

    state.similar_posts = [SimilarPost(**row) for row in rows]


async def _fetch_voice_profile(
    state: PostEvaluationState,
    settings: Settings,
    user_id: str,
    collector: Optional[RunMetadataCollector] = None,
) -> None:
    """Populate state.voice_profile from the subscriber's own top posts
    (dynamic style-profile prompting). Leaves it at None (the default) if
    there isn't enough data yet — see
    storage/vector_store.get_user_voice_profile()'s cold-start behavior.
    """

    def _fetch() -> Optional[dict]:
        conn = get_connection(settings)
        try:
            return get_user_voice_profile(conn, user_id)
        finally:
            conn.close()

    state.voice_profile = await run_timed_thread(
        collector,
        step_id="setup.voice_profile",
        label="Fetch voice profile",
        stage="setup",
        call_type="db",
        fn=_fetch,
    )


async def _fetch_draft_follower_count(
    settings: Settings,
    user_id: str,
    collector: Optional[RunMetadataCollector] = None,
) -> Optional[int]:
    """Look up the draft author's follower count from the profiles cache."""

    def _fetch() -> Optional[int]:
        conn = get_connection(settings)
        try:
            return get_follower_count(conn, user_id)
        finally:
            conn.close()

    return await run_timed_thread(
        collector,
        step_id="setup.follower_count",
        label="Fetch follower count",
        stage="setup",
        call_type="db",
        fn=_fetch,
    )


async def _gather_discoverability_context(
    draft_content: str,
    similar_posts: list,
    settings: Settings,
    *,
    use_google_trends: bool,
    collector: Optional[RunMetadataCollector] = None,
) -> tuple[Optional[dict], list[str]]:
    """Pre-compute corpus-grounded evidence for the SEO diagnostic worker."""

    def _fetch() -> tuple[Optional[dict], list[str]]:
        return gather_discoverability_context(
            draft_content,
            similar_posts,
            settings,
            use_google_trends=use_google_trends,
        )

    return await run_timed_thread(
        collector,
        step_id="setup.discoverability_context",
        label="Gather discoverability context",
        stage="setup",
        call_type="external",
        fn=_fetch,
    )


def _as_dict(output: Any) -> dict:
    """Normalize a PydanticAI agent's `result.output` into a plain dict.

    Agents may declare a structured `output_type` (a BaseModel subclass) or
    return a plain dict/string — state.predictor_result/diagnostics store
    plain dicts, so this coerces either shape consistently.
    """
    if isinstance(output, BaseModel):
        return output.model_dump()
    if isinstance(output, dict):
        return output
    return {"result": output}


def _agent_model_name() -> str:
    return pydantic_ai_gemini_model()


async def _run_agent_with_telemetry(
    collector: Optional[RunMetadataCollector],
    key: str,
    agent: EvaluationAgent,
    prompt: Any,
    deps: EvaluationDeps,
) -> Any:
    step_id = "agent.predictor" if key == "__predictor__" else f"agent.{key}"
    label = "Predictor" if key == "__predictor__" else key.title()
    return await run_agent_step(
        collector,
        step_id=step_id,
        label=label,
        stage="agent",
        agent=agent,
        prompt=prompt,
        deps=deps,
        model=_agent_model_name(),
    )


async def run_evaluation_cycle(
    draft_content: str,
    settings: Settings,
    predictor: Optional[EvaluationAgent] = None,
    diagnostics: Optional[dict[str, EvaluationAgent]] = None,
    finalize: Optional[FinalizeHook] = None,
    user_id: Optional[str] = None,
    use_voice_profile: bool = True,
    seo_mode: Optional[SeoDiscoverabilityMode] = None,
    use_google_trends: Optional[bool] = None,
    use_visual_diagnostics: Optional[bool] = None,
    image_url: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    image_media_type: Optional[str] = None,
    collector: Optional[RunMetadataCollector] = None,
    variant_strategy: Optional[str] = None,
    reembed_variant_neighbors: bool = False,
    neighbor_limit: int = 10,
) -> PostEvaluationState:
    """Run one full content-evaluation cycle for `draft_content`.

    A fresh PostEvaluationState is created per call (no shared module-level
    mutable state), so nothing leaks between separate calls/requests.

    Args:
        draft_content: the draft post text to evaluate.
        settings: loaded Settings (Gemini API key, database_url, etc).
        predictor: optional PydanticAI Agent (T3.2) — run concurrently with
            `diagnostics`, its structured output written to
            `state.predictor_result`. None (default) for T3.1's own scope,
            since the real Predictor Agent doesn't exist yet.
        diagnostics: optional dict of name -> PydanticAI Agent (T3.3) — each
            runs concurrently with `predictor` and with each other, its
            output written to `state.diagnostics[name]`. Empty (default)
            for T3.1's own scope.
        finalize: optional async callable run sequentially *after* stage 2
            (future hook for T3.4's Variant Optimisation Engine, which needs
            stage 2's collected diagnostics as input). None (default) for
            T3.1's own scope — nothing calls this yet.
        user_id: optional subscriber id (personalization). When given,
            neighbor retrieval is tenant-scoped to that user's own posts
            (falling back to the global corpus if they don't have enough,
            see find_similar()), and — if `use_voice_profile` is True — a
            derived voice profile is fetched and made available to every
            agent via `EvaluationDeps.voice_profile`.
        use_voice_profile: whether to fetch/apply the subscriber's voice
            profile when `user_id` is given. Ignored if `user_id` is None.
            Default True — this is opt-in only in the sense that it does
            nothing without a `user_id`; no separate flag is needed to
            "turn personalization on" once a user_id is supplied.
        seo_mode: SEO discoverability mode — ``corpus`` (default) grounds the
            SEO worker in the scraped dataset; ``gemini_only`` uses the
            legacy static prompt for A/B testing. Falls back to
            ``settings.seo_discoverability_mode`` when not given.
        use_google_trends: Tier 2 Google Trends toggle. None uses
            ``settings.google_trends_enabled`` (off by default; opt in via env or request).
            Always off when ``seo_mode`` is ``gemini_only``.
        use_visual_diagnostics: T7.9+T7.10 multimodal visual diagnostics. None uses
            ``settings.visual_diagnostics_enabled`` (off by default). Requires an image
            (URL or bytes); skipped with a note when enabled without an image.
        image_url: optional draft image URL for visual diagnostics.
        image_bytes / image_media_type: optional uploaded image for visual diagnostics.
        collector: optional telemetry collector; created automatically when None.
        variant_strategy: recorded in run_metadata for persistence/dashboard.
        reembed_variant_neighbors: recorded in run_metadata.
        neighbor_limit: how many nearest posts to retrieve (default 10, max 100).

    Returns:
        The populated PostEvaluationState. `predictor_result`, `diagnostics`,
        and `variants` stay at their empty defaults if no agents were
        supplied — expected until T3.2/T3.3/T3.4 land.
    """
    resolved_neighbor_limit = resolve_neighbor_limit(neighbor_limit)
    if collector is None:
        resolved_seo_mode_for_meta: SeoDiscoverabilityMode = seo_mode or settings.seo_discoverability_mode  # type: ignore[assignment]
        if resolved_seo_mode_for_meta not in ("corpus", "gemini_only"):
            resolved_seo_mode_for_meta = "corpus"
        collector = RunMetadataCollector(
            settings=settings,
            user_id=user_id,
            agent_model=_agent_model_name(),
            variant_strategy=variant_strategy,
            reembed_variant_neighbors=reembed_variant_neighbors,
            seo_mode=resolved_seo_mode_for_meta,
            neighbor_limit=resolved_neighbor_limit,
        )
    else:
        collector._neighbor_limit = resolved_neighbor_limit

    state = PostEvaluationState(draft_content=draft_content)

    await _gather_similar_posts(
        state,
        settings,
        user_id=user_id,
        collector=collector,
        neighbor_limit=resolved_neighbor_limit,
    )
    if user_id is not None and use_voice_profile:
        await _fetch_voice_profile(state, settings, user_id, collector=collector)

    draft_follower_count: Optional[int] = None
    if user_id is not None:
        draft_follower_count = await _fetch_draft_follower_count(settings, user_id, collector=collector)

    def _neighbor_prediction():
        return compute_neighbor_prediction(
            state.similar_posts,
            draft_follower_count=draft_follower_count,
        )

    neighbor_prediction = collector.record_timed(
        step_id="setup.neighbor_prediction",
        label="Compute neighbor prediction",
        stage="setup",
        call_type="compute",
        fn=_neighbor_prediction,
    )

    resolved_seo_mode: SeoDiscoverabilityMode = seo_mode or settings.seo_discoverability_mode  # type: ignore[assignment]
    if resolved_seo_mode not in ("corpus", "gemini_only"):
        resolved_seo_mode = "corpus"

    discoverability_context = None
    if resolved_seo_mode == "corpus":
        resolved_use_google_trends = resolve_use_google_trends(
            resolved_seo_mode,
            settings,
            use_google_trends=use_google_trends,
        )
        discoverability_context, context_warnings = await _gather_discoverability_context(
            draft_content,
            state.similar_posts,
            settings,
            use_google_trends=resolved_use_google_trends,
            collector=collector,
        )
        state.errors.extend(context_warnings)

    clarity_context = compute_clarity_metrics(draft_content)
    state.clarity_context = clarity_context

    resolved_visual = resolve_use_visual_diagnostics(
        settings, use_visual_diagnostics=use_visual_diagnostics
    )
    state.visual_diagnostics_requested = resolved_visual

    resolved_image_bytes: Optional[bytes] = None
    resolved_image_media: Optional[str] = None
    resolved_image_url: Optional[str] = None
    if resolved_visual:
        (
            resolved_image_bytes,
            resolved_image_media,
            resolved_image_url,
            image_warnings,
        ) = prepare_visual_image(
            image_url=image_url,
            image_bytes=image_bytes,
            image_media_type=image_media_type,
        )
        state.errors.extend(image_warnings)
        state.visual_image_provided = bool(
            resolved_image_bytes and resolved_image_media
        ) or bool(resolved_image_url)
        if not state.visual_image_provided:
            state.errors.append(
                "visual: skipped — enabled but no usable image provided "
                "(pass image_url or upload jpeg/png/webp)."
            )

    deps = EvaluationDeps(
        draft_content=draft_content,
        similar_posts=state.similar_posts,
        voice_profile=state.voice_profile,
        discoverability_context=discoverability_context,
        seo_mode=resolved_seo_mode,
        clarity_context=clarity_context,
        neighbor_prediction=neighbor_prediction,
        draft_follower_count=draft_follower_count,
        image_url=resolved_image_url,
        image_bytes=resolved_image_bytes,
        image_media_type=resolved_image_media,
    )

    diag_agents: dict[str, EvaluationAgent] = dict(diagnostics or {})
    run_visual = resolved_visual and state.visual_image_provided
    if run_visual and "visual" not in diag_agents:
        diag_agents["visual"] = build_visual_agent()

    keys: list[str] = []
    coros: list[Awaitable[Any]] = []
    text_prompt = build_evaluation_user_message(draft_content)
    if predictor is not None:
        keys.append("__predictor__")
        coros.append(
            _run_agent_with_telemetry(collector, "__predictor__", predictor, text_prompt, deps)
        )
    for name, agent in diag_agents.items():
        keys.append(name)
        prompt: Any = (
            build_visual_user_prompt(deps) if name == "visual" else text_prompt
        )
        coros.append(_run_agent_with_telemetry(collector, name, agent, prompt, deps))

    results = await asyncio.gather(*coros, return_exceptions=True)

    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            # One bad agent must not drop the other agents' already-written
            # state or crash the whole cycle — record it and move on.
            state.errors.append(f"{key}: {result}")
            continue
        output = _as_dict(result.output)
        if key == "__predictor__":
            from agents.predictor import PredictorOutput

            if isinstance(result.output, PredictorOutput) and neighbor_prediction:
                corrected = apply_deterministic_prediction(result.output, neighbor_prediction)
                output = corrected.model_dump()
            state.predictor_result = output
        else:
            state.diagnostics[key] = output

    if finalize is not None:
        await finalize(state)

    state.run_metadata = collector.finalize()
    save_run_metadata(state.run_metadata, settings)

    return state
