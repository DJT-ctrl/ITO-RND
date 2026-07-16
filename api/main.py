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

from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from pgvector.psycopg import register_vector
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from agents.diagnostics import build_diagnostic_agents
from agents.orchestrator import run_evaluation_cycle
from agents.predictor import build_predictor_agent
from agents.schemas import PostEvaluationState
from agents.variant_engine import build_variant_engine
from api.rate_limit import limiter, optional_rate_limit, rate_limit_exceeded_handler
from api.schemas import EvaluateRequest, SimilarPost, SimilarPostsRequest, SimilarPostsResponse
from api.security import ApiPrincipal, assert_user_id_authorized, configure_api_security, require_api_principal
from config.settings import load_settings, pydantic_ai_gemini_model
from processors.embedder import embed_query
from storage.vector_store import find_similar, get_connection
from telemetry.collector import RunMetadataCollector

settings = load_settings()
configure_api_security(settings)
_eval_model = pydantic_ai_gemini_model()
predictor_agent = build_predictor_agent(_eval_model)
diagnostic_agents = build_diagnostic_agents(_eval_model)

app = FastAPI(title="ITO Post Similarity API")
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/similar-posts", response_model=SimilarPostsResponse)
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


@app.post("/api/v1/evaluate", response_model=PostEvaluationState)
@optional_rate_limit(settings.api_rate_limit)
async def evaluate(
    request_body: EvaluateRequest,
    request: Request,
    principal: Optional[ApiPrincipal] = Depends(require_api_principal),
) -> PostEvaluationState:
    """Run the async evaluation cycle end-to-end over HTTP."""
    assert_user_id_authorized(principal, request_body.user_id)

    resolved_seo_mode = request_body.seo_mode or settings.seo_discoverability_mode
    collector = RunMetadataCollector(
        settings=settings,
        user_id=request_body.user_id,
        agent_model=_eval_model,
        variant_strategy=request_body.variant_strategy,
        reembed_variant_neighbors=request_body.reembed_variant_neighbors,
        seo_mode=resolved_seo_mode,
    )
    variant_hook = build_variant_engine(
        predictor_agent,
        strategy=request_body.variant_strategy,
        reembed_neighbors=request_body.reembed_variant_neighbors,
        settings=settings,
        collector=collector,
    )
    try:
        return await run_evaluation_cycle(
            request_body.content,
            settings,
            predictor=predictor_agent,
            diagnostics=diagnostic_agents,
            finalize=variant_hook,
            user_id=request_body.user_id,
            use_voice_profile=request_body.use_voice_profile,
            seo_mode=request_body.seo_mode,
            use_google_trends=request_body.use_google_trends,
            collector=collector,
            variant_strategy=request_body.variant_strategy,
            reembed_variant_neighbors=request_body.reembed_variant_neighbors,
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
