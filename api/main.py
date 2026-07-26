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

from agents.audience_critic import (
    AudienceCriticOutput,
    build_audience_critic_agent,
    run_audience_critic,
)
from agents.diagnostics import build_diagnostic_agents
from agents.orchestrator import run_evaluation_cycle
from agents.predictor import build_predictor_agent
from agents.schemas import PostEvaluationState
from agents.variant_engine import build_variant_engine
from api.schemas import (
    CritiqueRequest,
    EvaluateRequest,
    SimilarPost,
    SimilarPostsRequest,
    SimilarPostsResponse,
)
from config.settings import load_settings, pydantic_ai_gemini_model
from processors.embedder import embed_query
from storage.vector_store import find_similar, get_connection
from telemetry.collector import RunMetadataCollector

settings = load_settings()
_eval_model = pydantic_ai_gemini_model()
predictor_agent = build_predictor_agent(_eval_model)
diagnostic_agents = build_diagnostic_agents(_eval_model)
audience_critic_agent = build_audience_critic_agent(_eval_model)

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
        return await run_evaluation_cycle(
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


@app.post("/api/v1/critique", response_model=AudienceCriticOutput)
async def critique(request: CritiqueRequest) -> AudienceCriticOutput:
    """Independent synthetic-audience critic (T7.11–T7.13).

    Not part of the evaluate loop — does not affect predictor, diagnostics, or variants.
    """
    try:
        return await run_audience_critic(request.content, agent=audience_critic_agent)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
