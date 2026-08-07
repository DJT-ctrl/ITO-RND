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
"""

from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from pgvector.psycopg import register_vector
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from agents.audience_critic import (
    AudienceCriticOutput,
    build_audience_critic_agent,
    run_audience_critic,
)
from agents.cross_reference import build_cross_reference_analyst
from agents.cluster_coaching import build_cluster_coaching_engine
from agents.diagnostics import build_diagnostic_agents
from agents.diagnostics import list_diagnostic_specs
from agents.orchestrator import run_evaluation_cycle
from agents.predictor import build_predictor_agent
from agents.schemas import PostEvaluationState
from agents.synthesis import SynthesisResult, run_synthesis
from agents.variant_engine import build_variant_engine
from api.openapi_examples import (
    API_ERROR_EXAMPLE,
    EVALUATE_REQUEST_EXAMPLE,
    EVALUATE_RESPONSE_EXAMPLE,
    HEALTH_OK_EXAMPLE,
    SIMILAR_POSTS_REQUEST_EXAMPLE,
    SIMILAR_POSTS_RESPONSE_EXAMPLE,
    VALIDATION_ERROR_EXAMPLE,
)
from api.rate_limit import limiter, optional_rate_limit, rate_limit_exceeded_handler
from api.schemas import (
    API_VERSION,
    AgentCatalogResponse,
    AgentDescriptor,
    ApiErrorResponse,
    CritiqueRequest,
    EvaluateRequest,
    EvaluateResponse,
    HealthResponse,
    OptimiseRequest,
    SimilarPost,
    SimilarPostsRequest,
    SimilarPostsResponse,
    ValidationErrorResponse,
)
from api.security import ApiPrincipal, assert_user_id_authorized, configure_api_security, require_api_principal
from config.settings import load_settings, pydantic_ai_gemini_model
from feedback.runtime_flags import apply_overrides_to_settings
from processors.embedder import embed_query
from storage.vector_store import find_similar, get_connection, get_user_voice_profile
from telemetry.collector import RunMetadataCollector

settings = load_settings()
configure_api_security(settings)

# Lazy agent state — populated by _ensure_eval_agents() on first /evaluate.
# Tests may patch these module attributes directly (see tests/test_api.py).
_eval_model: Optional[str] = None
predictor_agent: Any = None
diagnostic_agents: Any = None
cross_reference_analyst: Any = None
audience_critic_agent: Any = None

_OPENAPI_DESCRIPTION = """
Public HTTP API for IntoTheOpen post evaluation and similarity retrieval.

## Versioning

All stable integration endpoints live under **`/api/v1/`**. See
`docs/api/VERSIONING.md` for deprecation and backward-compatibility rules.

## Errors

Documented error shapes (`ApiErrorResponse`, `ValidationErrorResponse`) are
stable for client generation. Runtime mapping to these envelopes is implemented
in issue #7; until then, validation failures return HTTP 422 as documented and
other failures may return a plain `detail` string.
""".strip()

_COMMON_ERROR_RESPONSES = {
    422: {
        "model": ValidationErrorResponse,
        "description": "Request validation failed.",
        "content": {"application/json": {"example": VALIDATION_ERROR_EXAMPLE}},
    },
    500: {
        "model": ApiErrorResponse,
        "description": "Unhandled server error (documented contract; runtime envelope in #7).",
        "content": {"application/json": {"example": API_ERROR_EXAMPLE}},
    },
}

app = FastAPI(
    title="IntoTheOpen API",
    version=API_VERSION,
    description=_OPENAPI_DESCRIPTION,
    openapi_tags=[
        {"name": "health", "description": "Liveness and API version probe."},
        {"name": "v1", "description": "Stable v1 contract for frontend integration."},
    ],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
if settings.api_rate_limit:
    app.add_middleware(SlowAPIMiddleware)

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


def _ensure_eval_agents() -> tuple[str, Any, Any, Any]:
    """Build predictor/diagnostic agents on first use (not at import).

    Raises HTTPException(503) with actionable config guidance if the provider
    or model cannot be constructed.
    """
    global _eval_model, predictor_agent, diagnostic_agents, cross_reference_analyst, audience_critic_agent

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

    if cross_reference_analyst is None:
        try:
            cross_reference_analyst = build_cross_reference_analyst(_eval_model)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Failed to initialize cross-reference analyst ({_eval_model!r}): {exc}. "
                    "Install pydantic-ai-slim[google]>=2.5,<3 and set GEMINI_API_KEY."
                ),
            ) from exc

    if audience_critic_agent is None:
        try:
            audience_critic_agent = build_audience_critic_agent(_eval_model)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Failed to initialize audience critic ({_eval_model!r}): {exc}. "
                    "Install pydantic-ai-slim[google]>=2.5,<3 and set GEMINI_API_KEY."
                ),
            ) from exc

    return _eval_model, predictor_agent, diagnostic_agents, cross_reference_analyst


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["health"],
    summary="Liveness check",
    responses={200: {"content": {"application/json": {"example": HEALTH_OK_EXAMPLE}}}},
)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get(
    "/api/v1/agents",
    response_model=AgentCatalogResponse,
    tags=["v1"],
    summary="List active backend agents",
    responses={
        200: {
            "description": "Current backend agent registry for frontend discovery.",
        },
        **_COMMON_ERROR_RESPONSES,
    },
)
@optional_rate_limit(settings.api_rate_limit)
def list_agents(request: Request) -> AgentCatalogResponse:
    diagnostics = list_diagnostic_specs()
    agents = [
        AgentDescriptor(
            id="predictor",
            name="Predictor",
            kind="predictor",
            stage="evaluation",
            description="Forecasts engagement from nearest-neighbor evidence.",
        )
    ]
    for key, spec in diagnostics.items():
        agents.append(
            AgentDescriptor(
                id=key,
                name=spec.get("title", key).title(),
                kind="diagnostic",
                stage="evaluation",
                description=spec.get("focus", "Diagnostic quality check."),
            )
        )
    agents.append(
        AgentDescriptor(
            id="cross_reference",
            name="Cross-Reference Analyst",
            kind="system",
            stage="reporting",
            description="Explains what stronger close historical matches do differently.",
        )
    )
    agents.append(
        AgentDescriptor(
            id="variant",
            name="Variant Engine",
            kind="variant",
            stage="optimization",
            description="Generates and ranks optimized rewrite variants.",
        )
    )
    return AgentCatalogResponse(agents=agents)


@app.post(
    "/api/v1/similar-posts",
    response_model=SimilarPostsResponse,
    tags=["v1"],
    summary="Find similar historical posts",
    responses={
        200: {
            "description": "Nearest-neighbor posts for the draft.",
            "content": {"application/json": {"example": SIMILAR_POSTS_RESPONSE_EXAMPLE}},
        },
        **_COMMON_ERROR_RESPONSES,
    },
)
@optional_rate_limit(settings.api_rate_limit)
def similar_posts(
    request_body: SimilarPostsRequest,
    request: Request,
    principal: Optional[ApiPrincipal] = Depends(require_api_principal),
) -> SimilarPostsResponse:
    assert_user_id_authorized(principal, request_body.user_id)

    try:
        query_vector, _prompt_tokens = embed_query(request_body.content, settings)
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
        rows = find_similar(conn, query_vector, limit=request_body.limit, user_id=request_body.user_id)
    finally:
        conn.close()

    return SimilarPostsResponse(
        query_content=request_body.content,
        results=[SimilarPost(**row) for row in rows],
    )


@app.post(
    "/api/v1/evaluate",
    response_model=EvaluateResponse,
    tags=["v1"],
    summary="Run the full multi-agent evaluation cycle",
    responses={
        200: {
            "description": "Evaluation cycle result.",
            "content": {"application/json": {"example": EVALUATE_RESPONSE_EXAMPLE}},
        },
        **_COMMON_ERROR_RESPONSES,
    },
)
@optional_rate_limit(settings.api_rate_limit)
async def evaluate(
    request_body: EvaluateRequest,
    request: Request,
    principal: Optional[ApiPrincipal] = Depends(require_api_principal),
) -> EvaluateResponse:
    """Run the async evaluation cycle end-to-end over HTTP."""
    assert_user_id_authorized(principal, request_body.user_id)
    runtime_settings = apply_overrides_to_settings(settings)

    eval_model, predictor, diagnostics, reference_analyst = _ensure_eval_agents()
    resolved_seo_mode = request_body.seo_mode or runtime_settings.seo_discoverability_mode
    collector = RunMetadataCollector(
        settings=runtime_settings,
        user_id=request_body.user_id,
        agent_model=eval_model,
        variant_strategy=request_body.variant_strategy,
        reembed_variant_neighbors=request_body.reembed_variant_neighbors,
        seo_mode=resolved_seo_mode,
        neighbor_limit=request_body.neighbor_limit,
    )
    variant_hook = build_variant_engine(
        predictor,
        strategy=request_body.variant_strategy,
        reembed_neighbors=request_body.reembed_variant_neighbors,
        settings=runtime_settings,
        collector=collector,
        neighbor_limit=request_body.neighbor_limit,
    )
    coaching_hook = (
        build_cluster_coaching_engine(runtime_settings, collector=collector)
        if runtime_settings.validation_cluster_coaching_enabled
        else None
    )

    async def finalize(state: PostEvaluationState) -> None:
        if coaching_hook is not None:
            await coaching_hook(state)
        await variant_hook(state)

    try:
        state: PostEvaluationState = await run_evaluation_cycle(
            request_body.content,
            runtime_settings,
            predictor=predictor,
            diagnostics=diagnostics,
            finalize=finalize,
            user_id=request_body.user_id,
            use_voice_profile=request_body.use_voice_profile,
            seo_mode=request_body.seo_mode,
            use_google_trends=request_body.use_google_trends,
            use_visual_diagnostics=request_body.use_visual_diagnostics,
            image_url=request_body.image_url,
            collector=collector,
            variant_strategy=request_body.variant_strategy,
            reembed_variant_neighbors=request_body.reembed_variant_neighbors,
            neighbor_limit=request_body.neighbor_limit,
            cross_reference_analyst=reference_analyst,
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return EvaluateResponse.model_validate(state.model_dump())


@app.post("/api/v1/critique", response_model=AudienceCriticOutput, tags=["v1"])
@optional_rate_limit(settings.api_rate_limit)
async def critique(
    request_body: CritiqueRequest,
    request: Request,
    principal: Optional[ApiPrincipal] = Depends(require_api_principal),
) -> AudienceCriticOutput:
    """Independent synthetic-audience critic (T7.11–T7.13).

    Not part of the evaluate loop — does not affect predictor, diagnostics, or variants.
    """
    _ensure_eval_agents()
    try:
        return await run_audience_critic(request_body.content, agent=audience_critic_agent)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/v1/optimise", response_model=SynthesisResult, tags=["v1"])
@optional_rate_limit(settings.api_rate_limit)
async def optimise(
    request_body: OptimiseRequest,
    request: Request,
    principal: Optional[ApiPrincipal] = Depends(require_api_principal),
) -> SynthesisResult:
    """Independent Stage 5 synthesis (T7.14–T7.16).

    Does not replace evaluate-loop variants. Soft-fails scoring into result.errors.
    """
    assert_user_id_authorized(principal, request_body.user_id)
    eval_model, predictor, _diagnostics, _reference_analyst = _ensure_eval_agents()
    voice_profile = None
    if request_body.user_id and request_body.use_voice_profile:
        conn = get_connection(settings)
        try:
            voice_profile = get_user_voice_profile(conn, request_body.user_id)
        finally:
            conn.close()

    try:
        return await run_synthesis(
            request_body.content,
            settings,
            primary_objection=request_body.primary_objection,
            baseline_percentile=request_body.baseline_percentile,
            baseline_total_engagement=request_body.baseline_total_engagement,
            voice_profile=voice_profile,
            user_id=request_body.user_id,
            predictor_agent=predictor,
            model=eval_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def custom_openapi():
    """Attach request-body examples after routes are registered."""
    if app.openapi_schema:
        return app.openapi_schema

    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    for path, path_item in schema.get("paths", {}).items():
        post = path_item.get("post")
        if not post:
            continue
        body = post.get("requestBody", {}).get("content", {}).get("application/json", {})
        if path.endswith("/similar-posts"):
            body["example"] = SIMILAR_POSTS_REQUEST_EXAMPLE
        elif path.endswith("/evaluate"):
            body["example"] = EVALUATE_REQUEST_EXAMPLE

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]
