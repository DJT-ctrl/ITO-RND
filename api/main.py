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
"""

from fastapi import FastAPI, HTTPException
from pgvector.psycopg import register_vector

from agents.diagnostics import build_diagnostic_agents
from agents.orchestrator import run_evaluation_cycle
from agents.predictor import build_predictor_agent
from agents.schemas import PostEvaluationState
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
from api.schemas import (
    API_VERSION,
    ApiErrorResponse,
    EvaluateRequest,
    EvaluateResponse,
    HealthResponse,
    SimilarPost,
    SimilarPostsRequest,
    SimilarPostsResponse,
    ValidationErrorResponse,
)
from config.settings import load_settings, pydantic_ai_gemini_model
from processors.embedder import embed_query
from storage.vector_store import find_similar, get_connection
from telemetry.collector import RunMetadataCollector

settings = load_settings()
_eval_model = pydantic_ai_gemini_model()
predictor_agent = build_predictor_agent(_eval_model)
diagnostic_agents = build_diagnostic_agents(_eval_model)

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


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["health"],
    summary="Liveness check",
    responses={200: {"content": {"application/json": {"example": HEALTH_OK_EXAMPLE}}}},
)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


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
async def evaluate(request: EvaluateRequest) -> EvaluateResponse:
    """Run the async evaluation cycle end-to-end over HTTP."""
    resolved_seo_mode = request.seo_mode or settings.seo_discoverability_mode
    collector = RunMetadataCollector(
        settings=settings,
        user_id=request.user_id,
        agent_model=_eval_model,
        variant_strategy=request.variant_strategy,
        reembed_variant_neighbors=request.reembed_variant_neighbors,
        seo_mode=resolved_seo_mode,
    )
    variant_hook = build_variant_engine(
        predictor_agent,
        strategy=request.variant_strategy,
        reembed_neighbors=request.reembed_variant_neighbors,
        settings=settings,
        collector=collector,
    )
    try:
        state: PostEvaluationState = await run_evaluation_cycle(
            request.content,
            settings,
            predictor=predictor_agent,
            diagnostics=diagnostic_agents,
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

    return EvaluateResponse.model_validate(state.model_dump())


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
