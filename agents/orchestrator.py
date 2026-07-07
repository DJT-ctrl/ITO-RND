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
from typing import Any, Awaitable, Callable, Optional

from pgvector.psycopg import register_vector
from pydantic import BaseModel
from pydantic_ai import Agent

from agents.schemas import EvaluationDeps, PostEvaluationState
from config.settings import Settings
from processors.embedder import embed_query
from storage.vector_store import find_similar, get_connection

# A PydanticAI agent sharing our EvaluationDeps as read-only context. T3.2's
# Predictor Agent and T3.3's Diagnostic Worker Agents will each be one of
# these, registered into run_evaluation_cycle below.
EvaluationAgent = Agent[EvaluationDeps, Any]

# Plain async hook (not necessarily an LLM call) for the sequential finalize
# stage — future extension point for T3.4.
FinalizeHook = Callable[[PostEvaluationState], Awaitable[None]]


async def _gather_similar_posts(state: PostEvaluationState, settings: Settings) -> None:
    """Populate state.similar_posts with the 10 nearest vector neighbors.

    Wraps the existing *synchronous* embed_query() (processors/embedder.py)
    and find_similar()/get_connection() (storage/vector_store.py) via
    asyncio.to_thread — both do blocking I/O (a Gemini HTTP call, a
    blocking psycopg query) and would otherwise stall the event loop during
    the concurrent evaluation stage that follows.

    Opens and closes its own DB connection inside the offloaded call, same
    per-request pattern as api/main.py — nothing is held open across the
    concurrent stage, which is the "no leaking memory" half of Erdal's
    success criterion.
    """

    def _fetch() -> list[dict]:
        query_vector = embed_query(state.draft_content, settings)
        conn = get_connection(settings)
        try:
            register_vector(conn)
            return find_similar(conn, query_vector, limit=10)
        finally:
            conn.close()

    rows = await asyncio.to_thread(_fetch)
    from api.schemas import SimilarPost

    state.similar_posts = [SimilarPost(**row) for row in rows]


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


async def run_evaluation_cycle(
    draft_content: str,
    settings: Settings,
    predictor: Optional[EvaluationAgent] = None,
    diagnostics: Optional[dict[str, EvaluationAgent]] = None,
    finalize: Optional[FinalizeHook] = None,
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

    Returns:
        The populated PostEvaluationState. `predictor_result`, `diagnostics`,
        and `variants` stay at their empty defaults if no agents were
        supplied — expected until T3.2/T3.3/T3.4 land.
    """
    state = PostEvaluationState(draft_content=draft_content)

    await _gather_similar_posts(state, settings)

    deps = EvaluationDeps(draft_content=draft_content, similar_posts=state.similar_posts)

    keys: list[str] = []
    coros: list[Awaitable[Any]] = []
    if predictor is not None:
        keys.append("__predictor__")
        coros.append(predictor.run(draft_content, deps=deps))
    for name, agent in (diagnostics or {}).items():
        keys.append(name)
        coros.append(agent.run(draft_content, deps=deps))

    results = await asyncio.gather(*coros, return_exceptions=True)

    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            # One bad agent must not drop the other agents' already-written
            # state or crash the whole cycle — record it and move on.
            state.errors.append(f"{key}: {result}")
            continue
        output = _as_dict(result.output)
        if key == "__predictor__":
            state.predictor_result = output
        else:
            state.diagnostics[key] = output

    if finalize is not None:
        await finalize(state)

    return state
