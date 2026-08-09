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
from agents.synthesis import SynthesisResult, run_synthesis
from agents.variant_engine import build_variant_engine
from api.schemas import (
    CritiqueRequest,
    EvaluateRequest,
    OptimiseRequest,
    SimilarPost,
    SimilarPostsRequest,
    SimilarPostsResponse,
    SubscriberEvidenceBriefRequest,
    SubscriberEvidenceJobResponse,
    SubscriberEvidencePlanResponse,
    SubscriberEvidenceReceiptResponse,
)
from config.settings import load_settings, pydantic_ai_gemini_model
from phase_19.models import SubscriberEvidenceBrief
from phase_19.service import (
    SubscriberEvidenceError,
    SubscriberEvidenceNotFoundError,
    approve_baseline,
    get_baseline,
    list_jobs,
    list_receipts,
    pause_baseline,
    propose_baseline,
    resume_baseline,
)
from processors.embedder import embed_query
from storage.vector_store import find_similar, get_connection, get_user_voice_profile
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


def _evidence_response(brief: dict, plan: dict) -> SubscriberEvidencePlanResponse:
    return SubscriberEvidencePlanResponse(brief=brief, plan=plan)


@app.post(
    "/api/v1/subscriber-evidence/briefs",
    response_model=SubscriberEvidencePlanResponse,
    status_code=201,
)
def create_subscriber_evidence_brief(
    request: SubscriberEvidenceBriefRequest,
) -> SubscriberEvidencePlanResponse:
    """Create or revise a consented brief and propose a bounded baseline plan.

    This endpoint does not call an external provider or enqueue collection.
    A revised brief supersedes its earlier approved plan and requires fresh
    approval before the Release B worker may spend.
    """
    brief = SubscriberEvidenceBrief(
        subscriber_id=request.subscriber_id,
        public_profile_url=request.public_profile_url,
        profile_authorized=request.profile_authorized,
        role_description=request.role_description,
        primary_niche=request.primary_niche,
        sub_niche=request.sub_niche,
        target_audience=request.target_audience,
        objectives=tuple(request.objectives),
        locale=request.locale,
        seed_accounts=tuple(request.seed_accounts),
    )
    try:
        saved_brief, plan = propose_baseline(brief, settings=settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SubscriberEvidenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _evidence_response(saved_brief, plan)


@app.get(
    "/api/v1/subscriber-evidence/briefs/{subscriber_id}",
    response_model=SubscriberEvidencePlanResponse,
)
def read_subscriber_evidence_brief(subscriber_id: str) -> SubscriberEvidencePlanResponse:
    """Get one subscriber's brief and current reviewed baseline plan."""
    try:
        brief, plan = get_baseline(subscriber_id, settings=settings)
    except SubscriberEvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SubscriberEvidenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _evidence_response(brief, plan)


@app.post(
    "/api/v1/subscriber-evidence/briefs/{subscriber_id}/approve",
    response_model=SubscriberEvidencePlanResponse,
)
def approve_subscriber_evidence_plan(subscriber_id: str) -> SubscriberEvidencePlanResponse:
    """Approve the current plan. Enables the collection worker; does not scrape inline."""
    try:
        brief, plan = approve_baseline(subscriber_id, settings=settings)
    except SubscriberEvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SubscriberEvidenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _evidence_response(brief, plan)


@app.post(
    "/api/v1/subscriber-evidence/briefs/{subscriber_id}/pause",
    response_model=SubscriberEvidencePlanResponse,
)
def pause_subscriber_evidence(subscriber_id: str) -> SubscriberEvidencePlanResponse:
    """Pause automated collection for an approved brief."""
    try:
        brief, plan = pause_baseline(subscriber_id, settings=settings)
    except SubscriberEvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SubscriberEvidenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _evidence_response(brief, plan)


@app.post(
    "/api/v1/subscriber-evidence/briefs/{subscriber_id}/resume",
    response_model=SubscriberEvidencePlanResponse,
)
def resume_subscriber_evidence(subscriber_id: str) -> SubscriberEvidencePlanResponse:
    """Resume a paused brief that still has an approved plan."""
    try:
        brief, plan = resume_baseline(subscriber_id, settings=settings)
    except SubscriberEvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SubscriberEvidenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _evidence_response(brief, plan)


@app.get(
    "/api/v1/subscriber-evidence/briefs/{subscriber_id}/receipts",
    response_model=list[SubscriberEvidenceReceiptResponse],
)
def read_subscriber_evidence_receipts(
    subscriber_id: str,
) -> list[SubscriberEvidenceReceiptResponse]:
    """Return recent collection receipts for one subscriber."""
    try:
        rows = list_receipts(subscriber_id, settings=settings)
    except SubscriberEvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SubscriberEvidenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return [SubscriberEvidenceReceiptResponse(**row) for row in rows]


@app.get(
    "/api/v1/subscriber-evidence/briefs/{subscriber_id}/jobs",
    response_model=list[SubscriberEvidenceJobResponse],
)
def read_subscriber_evidence_jobs(
    subscriber_id: str,
) -> list[SubscriberEvidenceJobResponse]:
    """Return recent collection jobs for operator review."""
    try:
        rows = list_jobs(subscriber_id, settings=settings)
    except SubscriberEvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SubscriberEvidenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return [SubscriberEvidenceJobResponse(**row) for row in rows]


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
        neighbor_limit=request.neighbor_limit,
    )
    variant_hook = build_variant_engine(
        predictor_agent,
        strategy=request.variant_strategy,
        reembed_neighbors=request.reembed_variant_neighbors,
        settings=settings,
        collector=collector,
        neighbor_limit=request.neighbor_limit,
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
            use_visual_diagnostics=request.use_visual_diagnostics,
            image_url=request.image_url,
            collector=collector,
            variant_strategy=request.variant_strategy,
            reembed_variant_neighbors=request.reembed_variant_neighbors,
            neighbor_limit=request.neighbor_limit,
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


@app.post("/api/v1/optimise", response_model=SynthesisResult)
async def optimise(request: OptimiseRequest) -> SynthesisResult:
    """Independent Stage 5 synthesis (T7.14–T7.16).

    Does not replace evaluate-loop variants. Soft-fails scoring into result.errors.
    """
    voice_profile = None
    if request.user_id and request.use_voice_profile:
        conn = get_connection(settings)
        try:
            voice_profile = get_user_voice_profile(conn, request.user_id)
        finally:
            conn.close()

    try:
        return await run_synthesis(
            request.content,
            settings,
            primary_objection=request.primary_objection,
            baseline_percentile=request.baseline_percentile,
            baseline_total_engagement=request.baseline_total_engagement,
            voice_profile=voice_profile,
            user_id=request.user_id,
            predictor_agent=predictor_agent,
            model=_eval_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
