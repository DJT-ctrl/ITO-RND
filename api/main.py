"""FastAPI app: draft evaluation, corpus ingest, feedback, personalization, stats.

Settings load once at module scope. A fresh DB connection opens per request
where needed (connection pooling is a future optimization).
"""

from __future__ import annotations

from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
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
from api import job_store
from api.corpus_ops import get_corpus_stats, run_corpus_ingest
from api.schemas import (
    AllStatsResponse,
    AsyncJobResponse,
    BudgetStatsResponse,
    CompanyCorpusCollectRequest,
    CompanyCorpusCollectResponse,
    CompanyResolveItem,
    CompanyResolveRequest,
    CompanyResolveResponse,
    CorpusIngestRequest,
    CorpusStatsResponse,
    CritiqueRequest,
    EvaluateRequest,
    FeedbackCoverageResponse,
    FeedbackRunRequest,
    FeedbackRunResponse,
    FeedbackStatsResponse,
    OptimiseRequest,
    SimilarPost,
    SimilarPostsRequest,
    SimilarPostsResponse,
    SubscriberEvidenceBriefRequest,
    SubscriberEvidenceJobResponse,
    SubscriberEvidencePlanResponse,
    SubscriberEvidencePostResponse,
    SubscriberEvidenceReceiptResponse,
    SubscriberEvidenceRefreshResponse,
    SubscriberEvidenceStatusResponse,
)
from api.stats_ops import get_all_stats, get_budget_stats, get_feedback_stats
from config.settings import load_settings, pydantic_ai_gemini_model
from feedback.batch import run_feedback_worker
from feedback.schemas import FeedbackRecord
from feedback.store import list_pending_feedback_for_review
from phase_19.models import SubscriberEvidenceBrief
from phase_19.service import (
    SubscriberEvidenceError,
    SubscriberEvidenceNotFoundError,
    approve_baseline,
    get_baseline,
    get_evidence_status,
    list_accepted_posts,
    list_jobs,
    list_receipts,
    pause_baseline,
    propose_baseline,
    refresh_subscriber_now,
    resume_baseline,
)
from processors.embedder import embed_query
from storage.vector_store import (
    create_schema,
    find_similar,
    get_connection,
    get_user_voice_profile,
)
from telemetry.collector import RunMetadataCollector

settings = load_settings()
_eval_model = pydantic_ai_gemini_model()
predictor_agent = build_predictor_agent(_eval_model)
diagnostic_agents = build_diagnostic_agents(_eval_model)
audience_critic_agent = build_audience_critic_agent(_eval_model)

app = FastAPI(
    title="ITO Post Similarity API",
    description="Product HTTP API for draft evaluation, corpus ingest, feedback, and personalization.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Telemetry: expose Prometheus metrics at /metrics for the local Prometheus
# scraper (see docker-compose.yml's `prometheus` service + deploy/telemetry/).
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


def _job_response(row: dict[str, Any]) -> AsyncJobResponse:
    return AsyncJobResponse(**row)


def _run_corpus_job(
    job_id: str,
    *,
    mode: str,
    processed_file: str | None,
    embeddings_file: str | None,
    limit: int | None,
) -> None:
    job_store.mark_running(job_id)
    try:
        result = run_corpus_ingest(
            mode=mode,  # type: ignore[arg-type]
            processed_file=processed_file,
            embeddings_file=embeddings_file,
            limit=limit,
            settings=settings,
        )
        job_store.mark_completed(job_id, result)
    except Exception as exc:  # noqa: BLE001 — surface any failure on the job record
        job_store.mark_failed(job_id, str(exc))


# ---------------------------------------------------------------------------
# Phase 19 — subscriber evidence / personalization
# ---------------------------------------------------------------------------


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


@app.get(
    "/api/v1/subscriber-evidence/briefs/{subscriber_id}/status",
    response_model=SubscriberEvidenceStatusResponse,
)
def read_subscriber_evidence_status(
    subscriber_id: str,
) -> SubscriberEvidenceStatusResponse:
    """Coverage + budget snapshot for the personalization strength UI."""
    try:
        row = get_evidence_status(subscriber_id, settings=settings)
    except SubscriberEvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SubscriberEvidenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return SubscriberEvidenceStatusResponse(**row)


@app.get(
    "/api/v1/subscriber-evidence/briefs/{subscriber_id}/posts",
    response_model=list[SubscriberEvidencePostResponse],
)
def read_subscriber_evidence_posts(
    subscriber_id: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[SubscriberEvidencePostResponse]:
    """Accepted evidence posts with preview text and LinkedIn URLs."""
    try:
        rows = list_accepted_posts(subscriber_id, settings=settings, limit=limit)
    except SubscriberEvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SubscriberEvidenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return [SubscriberEvidencePostResponse(**row) for row in rows]


@app.post(
    "/api/v1/subscriber-evidence/briefs/{subscriber_id}/refresh-now",
    response_model=SubscriberEvidenceRefreshResponse,
)
def refresh_subscriber_evidence_now(
    subscriber_id: str,
) -> SubscriberEvidenceRefreshResponse:
    """Run one collection cycle now (may call Apify and spend budget)."""
    try:
        row = refresh_subscriber_now(subscriber_id, settings=settings)
    except SubscriberEvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SubscriberEvidenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SubscriberEvidenceRefreshResponse(**row)


# ---------------------------------------------------------------------------
# Draft studio — compare / evaluate / critique / optimise
# ---------------------------------------------------------------------------


@app.post("/api/v1/similar-posts", response_model=SimilarPostsResponse)
def similar_posts(request: SimilarPostsRequest) -> SimilarPostsResponse:
    try:
        query_vector, _prompt_tokens = embed_query(request.content, settings)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    conn = get_connection(settings)
    try:
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


# ---------------------------------------------------------------------------
# Corpus — add analysed posts to the vector DB
# ---------------------------------------------------------------------------


@app.post(
    "/api/v1/corpus/ingest",
    response_model=AsyncJobResponse,
    status_code=202,
)
def corpus_ingest(
    request: CorpusIngestRequest,
    background_tasks: BackgroundTasks,
) -> AsyncJobResponse:
    """Queue analyse→embed→pgvector (or ingest-only) work as a background job."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not set.")
    meta = {
        "mode": request.mode,
        "processed_file": request.processed_file,
        "embeddings_file": request.embeddings_file,
        "limit": request.limit,
    }
    job = job_store.create_job("corpus_ingest", meta=meta)
    background_tasks.add_task(
        _run_corpus_job,
        job["id"],
        mode=request.mode,
        processed_file=request.processed_file,
        embeddings_file=request.embeddings_file,
        limit=request.limit,
    )
    return _job_response(job)


@app.get("/api/v1/corpus/jobs/{job_id}", response_model=AsyncJobResponse)
def corpus_job_status(job_id: str) -> AsyncJobResponse:
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    return _job_response(job)


@app.get("/api/v1/corpus/stats", response_model=CorpusStatsResponse)
def corpus_stats() -> CorpusStatsResponse:
    try:
        return CorpusStatsResponse(**get_corpus_stats(settings=settings))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Feedback loop
# ---------------------------------------------------------------------------


@app.post("/api/v1/feedback/run", response_model=FeedbackRunResponse)
def feedback_run(request: FeedbackRunRequest | None = None) -> FeedbackRunResponse:
    """Claim and process pending feedback_jobs (template + optional hybrid)."""
    body = request or FeedbackRunRequest()
    try:
        result = run_feedback_worker(settings, limit=body.limit)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FeedbackRunResponse(
        claimed=result.claimed,
        succeeded=result.succeeded,
        failed=result.failed,
        dead_lettered=result.dead_lettered,
    )


@app.get("/api/v1/feedback/coverage", response_model=FeedbackCoverageResponse)
def feedback_coverage() -> FeedbackCoverageResponse:
    try:
        stats = get_feedback_stats(settings=settings)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FeedbackCoverageResponse(**stats["coverage"])


@app.get("/api/v1/feedback/review", response_model=list[FeedbackRecord])
def feedback_review(
    limit: int = Query(default=30, ge=1, le=200),
) -> list[FeedbackRecord]:
    """Pending hybrid feedback rows awaiting approve/reject."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not set.")
    conn = get_connection(settings)
    try:
        create_schema(conn)
        return list_pending_feedback_for_review(conn, limit=limit)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@app.get("/api/v1/stats/corpus", response_model=CorpusStatsResponse)
def stats_corpus() -> CorpusStatsResponse:
    return corpus_stats()


@app.get("/api/v1/stats/feedback", response_model=FeedbackStatsResponse)
def stats_feedback() -> FeedbackStatsResponse:
    try:
        row = get_feedback_stats(settings=settings)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FeedbackStatsResponse(**row)


@app.get("/api/v1/stats/budget", response_model=BudgetStatsResponse)
def stats_budget() -> BudgetStatsResponse:
    return BudgetStatsResponse(**get_budget_stats(settings=settings))


@app.get("/api/v1/stats", response_model=AllStatsResponse)
def stats_all() -> AllStatsResponse:
    row = get_all_stats(settings=settings)
    return AllStatsResponse(
        corpus=CorpusStatsResponse(**row["corpus"]),
        feedback=FeedbackStatsResponse(**row["feedback"]),
        budget=BudgetStatsResponse(**row["budget"]),
    )


# ---------------------------------------------------------------------------
# Company Search & Bulk Corpus Ingestion
# ---------------------------------------------------------------------------


@app.post("/api/v1/companies/resolve-urls", response_model=CompanyResolveResponse)
def resolve_company_linkedin_urls(request: CompanyResolveRequest) -> CompanyResolveResponse:
    """Resolve bulk company names or URLs to canonical LinkedIn company URLs."""
    from processors.company_collector import parse_bulk_company_input, resolve_company_urls

    parsed = parse_bulk_company_input(request.companies)
    if not parsed:
        raise HTTPException(status_code=400, detail="No company names or URLs provided.")

    resolved_items = resolve_company_urls(parsed, settings=settings)
    return CompanyResolveResponse(
        results=[
            CompanyResolveItem(
                input_text=item.input_text,
                company_name=item.company_name,
                linkedin_url=item.linkedin_url,
                slug=item.slug,
                confidence=item.confidence,
                status=item.status,
                notes=item.notes,
            )
            for item in resolved_items
        ]
    )


@app.post("/api/v1/corpus/company-collect", response_model=CompanyCorpusCollectResponse)
def company_corpus_collect(
    request: CompanyCorpusCollectRequest,
    background_tasks: BackgroundTasks,
) -> CompanyCorpusCollectResponse:
    """Scrape 10 most recent posts from company LinkedIn URLs and ingest into pgvector."""
    from processors.company_collector import parse_bulk_company_input, run_company_corpus_flow

    parsed = parse_bulk_company_input(request.companies)
    if not parsed:
        raise HTTPException(status_code=400, detail="No company names or URLs provided.")

    if not settings.apify_api_token:
        raise HTTPException(status_code=503, detail="APIFY_API_TOKEN is not set.")

    if request.run_async:
        job_id = job_store.create_job(
            "company_corpus_collect",
            meta={
                "companies": parsed,
                "max_posts": request.max_posts_per_company,
                "with_gemini": request.with_gemini,
            },
        )

        def _bg():
            job_store.mark_running(job_id)
            try:
                res = run_company_corpus_flow(
                    parsed,
                    max_posts_per_company=request.max_posts_per_company,
                    settings=settings,
                    with_gemini=request.with_gemini,
                )
                if res.status == "success":
                    job_store.mark_completed(
                        job_id,
                        result={
                            "total_posts_scraped": res.total_posts_scraped,
                            "total_posts_ingested": res.total_posts_ingested,
                            "raw_file_path": res.raw_file_path,
                            "analysed_jsonl": res.analysed_jsonl,
                            "embeddings_path": res.embeddings_path,
                            "apify_cost_usd": res.apify_cost_usd,
                        },
                    )
                else:
                    job_store.mark_failed(job_id, error="; ".join(res.errors))
            except Exception as exc:
                job_store.mark_failed(job_id, error=str(exc))

        background_tasks.add_task(_bg)
        return CompanyCorpusCollectResponse(
            status="queued",
            job_id=job_id,
        )

    res = run_company_corpus_flow(
        parsed,
        max_posts_per_company=request.max_posts_per_company,
        settings=settings,
        with_gemini=request.with_gemini,
    )

    return CompanyCorpusCollectResponse(
        status=res.status,
        resolved_companies=[
            CompanyResolveItem(
                input_text=item.input_text,
                company_name=item.company_name,
                linkedin_url=item.linkedin_url,
                slug=item.slug,
                confidence=item.confidence,
                status=item.status,
                notes=item.notes,
            )
            for item in res.resolved_companies
        ],
        total_posts_scraped=res.total_posts_scraped,
        total_posts_ingested=res.total_posts_ingested,
        raw_file_path=res.raw_file_path,
        analysed_jsonl=res.analysed_jsonl,
        embeddings_path=res.embeddings_path,
        apify_cost_usd=res.apify_cost_usd,
        errors=res.errors,
    )

