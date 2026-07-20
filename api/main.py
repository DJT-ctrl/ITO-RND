"""FastAPI app (T2.1/T2.2): a health check + the cosine-similarity retrieval
endpoint.

Handler flow for POST /api/v1/similar-posts:
  1. embed_query(content, settings)  — embed the incoming draft text
     (task_type="RETRIEVAL_QUERY", see processors/embedder.py).
  2. find_similar(conn, vector, limit) — cosine-distance nearest-neighbour
     lookup against the halfvec(3072) HNSW index (storage/vector_store.py).
  3. Wrap the returned rows into SimilarPost objects.

Settings are loaded once at module scope (same pattern every other entry
point in this repo uses). A fresh DB connection is opened per request —
simplest correct option for this phase's scale; a connection pool is a
legitimate future optimization but is scope creep for now (see
PhaseT2plan.md Decision #3).

Issue #1: predictor/diagnostic agents are built lazily on first /evaluate
request so a provider mismatch cannot crash the process at import time
(GET /health and similar-posts stay up).

CI integration (issue #10): when ``CI_EVALUATE_STUB=true``, ``/evaluate``
skips LLM agents and returns a canned ``PostEvaluationState`` after a real
DB neighbor fetch. Agents are never constructed so the API can boot without
a live Gemini key.
"""

import os
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pgvector.psycopg import register_vector

from agents.diagnostics import build_diagnostic_agents
from agents.orchestrator import run_evaluation_cycle
from agents.predictor import build_predictor_agent
from agents.schemas import PostEvaluationState
from agents.variant_engine import build_variant_engine
from api.schemas import EvaluateRequest, SimilarPost, SimilarPostsRequest, SimilarPostsResponse
from config.settings import load_settings, pydantic_ai_gemini_model
from processors.embedder import EMBEDDING_MODEL_VERSION, embed_query
from storage.vector_store import find_similar, get_connection
from telemetry.collector import RunMetadataCollector

settings = load_settings()

_ci_evaluate_stub = os.getenv("CI_EVALUATE_STUB", "").lower() in ("1", "true", "yes")

# Lazy agent state — populated by _ensure_eval_agents() on first /evaluate.
# Tests may patch these module attributes directly (see tests/test_api.py).
# When CI_EVALUATE_STUB is set, agents stay unset and /evaluate uses the stub.
_eval_model: Optional[str] = None
predictor_agent: Any = None
diagnostic_agents: Any = None

app = FastAPI(title="ITO Post Similarity API")

# Telemetry: expose Prometheus metrics at /metrics for the local Prometheus
# scraper (see docker-compose.yml's `prometheus` service + deploy/telemetry/).
# This publishes request rate, latency histograms, and status-code counters
# for every route — the app-level half of the monolith stack's telemetry
# (cAdvisor/node-exporter cover the container/host half).
#
# Imported optionally so the app — and the existing mocked test suite — still
# runs if prometheus-fastapi-instrumentator isn't installed in a given env.
try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
except ImportError:
    pass


def _ensure_eval_agents() -> tuple[str, Any, Any]:
    """Build predictor/diagnostic agents on first use (not at import).

    Raises HTTPException(503) with actionable config guidance if the provider
    or model cannot be constructed.
    """
    global _eval_model, predictor_agent, diagnostic_agents

    if _eval_model is None:
        try:
            _eval_model = pydantic_ai_gemini_model()
        except ValueError as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Agent model configuration invalid: {exc}. "
                    "Set AGENT_GEMINI_MODEL (e.g. gemini-2.5-flash-lite) in .env."
                ),
            ) from exc

    if predictor_agent is None:
        try:
            predictor_agent = build_predictor_agent(_eval_model)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Failed to initialize predictor agent ({_eval_model!r}): {exc}. "
                    "Install pydantic-ai-slim[google]>=2.5,<3 and set GEMINI_API_KEY. "
                    "Use the google: provider prefix (legacy google-gla: is not supported)."
                ),
            ) from exc

    if diagnostic_agents is None:
        try:
            diagnostic_agents = build_diagnostic_agents(_eval_model)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Failed to initialize diagnostic agents ({_eval_model!r}): {exc}. "
                    "Install pydantic-ai-slim[google]>=2.5,<3 and set GEMINI_API_KEY."
                ),
            ) from exc

    return _eval_model, predictor_agent, diagnostic_agents


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/similar-posts", response_model=SimilarPostsResponse)
def similar_posts(request: SimilarPostsRequest) -> SimilarPostsResponse:
    try:
        query_vector, _prompt_tokens = embed_query(request.content, settings)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    conn = get_connection(settings)
    try:
        # get_connection() intentionally doesn't register the pgvector
        # adapter (see its docstring — the `vector` extension may not exist
        # on a brand-new database). Here, the schema is already assumed to
        # exist (this is a read-only query endpoint), so it's safe to
        # register the adapter immediately so `query_vector` (a numpy
        # array) can be passed directly as a query parameter.
        register_vector(conn)
        rows = find_similar(conn, query_vector, limit=request.limit, user_id=request.user_id)
    finally:
        conn.close()

    return SimilarPostsResponse(
        query_content=request.content,
        results=[SimilarPost(**row) for row in rows],
    )


@app.post("/api/v1/evaluate", response_model=PostEvaluationState)
async def evaluate(request: EvaluateRequest) -> PostEvaluationState:
    """Run the async evaluation cycle end-to-end over HTTP."""
    if _ci_evaluate_stub:
        return _evaluate_ci_stub(request)

    eval_model, predictor, diagnostics = _ensure_eval_agents()
    resolved_seo_mode = request.seo_mode or settings.seo_discoverability_mode
    collector = RunMetadataCollector(
        settings=settings,
        user_id=request.user_id,
        agent_model=eval_model,
        variant_strategy=request.variant_strategy,
        reembed_variant_neighbors=request.reembed_variant_neighbors,
        seo_mode=resolved_seo_mode,
    )
    variant_hook = build_variant_engine(
        predictor,
        strategy=request.variant_strategy,
        reembed_neighbors=request.reembed_variant_neighbors,
        settings=settings,
        collector=collector,
    )
    try:
        return await run_evaluation_cycle(
            request.content,
            settings,
            predictor=predictor,
            diagnostics=diagnostics,
            finalize=variant_hook,
            user_id=request.user_id,
            use_voice_profile=request.use_voice_profile,
            seo_mode=request.seo_mode,
            use_google_trends=request.use_google_trends,
            collector=collector,
            variant_strategy=request.variant_strategy,
            reembed_variant_neighbors=request.reembed_variant_neighbors,
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _evaluate_ci_stub(request: EvaluateRequest) -> PostEvaluationState:
    """CI-only evaluate path: real embed + DB neighbors, canned LLM fields."""
    try:
        query_vector, _prompt_tokens = embed_query(request.content, settings)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    conn = get_connection(settings)
    try:
        register_vector(conn)
        rows = find_similar(conn, query_vector, limit=10, user_id=request.user_id)
    finally:
        conn.close()

    similar = [SimilarPost(**row) for row in rows]
    return PostEvaluationState(
        draft_content=request.content,
        similar_posts=similar,
        predictor_result={
            "engagement_percentile": 72.0,
            "rationale": "ci-evaluate-stub",
        },
        diagnostics={
            "seo": {"score": 0.8, "notes": "ci-evaluate-stub"},
            "clarity": {"score": 0.75, "notes": "ci-evaluate-stub"},
            "tone": {"score": 0.7, "notes": "ci-evaluate-stub"},
        },
        variants=[],
        errors=[],
        query_embedding=query_vector.tolist(),
        embedding_model_version=EMBEDDING_MODEL_VERSION,
    )
