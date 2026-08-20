"""Pydantic request/response models for the FastAPI HTTP contract.

FastAPI generates OpenAPI at `/docs` and `/openapi.json` from these models.
Human-readable frontend docs live in `API.md` at the repo root.
"""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SimilarPostsRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Draft post text to find similar posts for")
    limit: int = Field(default=10, ge=1, le=50)
    user_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional subscriber id. When given, retrieval is scoped to that subscriber's own "
            "posts first, falling back to the global corpus automatically if they don't have "
            "enough of their own yet (cold start)."
        ),
    )


class SimilarPost(BaseModel):
    post_id: str
    content: str
    likes: int
    comments: int
    shares: int
    total_engagement: int
    engagement_percentile: float
    engagement_zscore: float
    cosine_distance: float
    # Optional follower-normalization (T6 Point 1). Populated only for posts
    # that went through processors/run_pipeline.py's
    # --with-profile-enrichment path AND had a resolvable follower count —
    # None otherwise, so this is a pure additive field: existing callers
    # that never used profile enrichment see no behavior change.
    follower_count: Optional[int] = None
    engagement_rate: Optional[float] = None
    audience_adjusted_percentile: Optional[float] = None
    # Optional discoverability metadata for Tier 1 SEO neighbor summaries.
    hashtag_count: Optional[int] = None
    word_count: Optional[int] = None
    topic: Optional[str] = None
    niche: Optional[str] = None
    hook_type: Optional[str] = None
    # Phase 11: age when neighbor engagement was measured (hours since publish).
    posted_at: Optional[datetime] = None
    engagement_age_hours: Optional[float] = None


class SimilarPostsResponse(BaseModel):
    query_content: str
    results: list[SimilarPost]


class EvaluateRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Draft post text to evaluate")
    neighbor_limit: int = Field(
        default=10,
        ge=10,
        le=100,
        description=(
            "How many nearest historical posts to retrieve for grounding and the "
            "comparison surface (default 10, max 100)."
        ),
    )
    variant_strategy: Literal["dimension", "narrative", "tiered"] = Field(
        default="dimension",
        description=(
            "Which distinctness axis the T3.4 Variant Optimisation Engine should use: "
            "'dimension' (one variant per SEO/clarity/tone diagnostic), 'narrative' "
            "(different hook/story angles), or 'tiered' (safe/moderate/bold rewrite)."
        ),
    )
    reembed_variant_neighbors: bool = Field(
        default=False,
        description=(
            "If true, each of the 3 variants re-embeds its own text and fetches its own "
            "nearest historical neighbors before being scored (more accurate when a variant "
            "shifts topic/angle, at the cost of up to 3 extra Gemini embed calls + DB queries). "
            "If false (default), all variants are scored against the original draft's shared "
            "neighbors (cheaper, and keeps all 3 compared against one consistent baseline)."
        ),
    )
    user_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional subscriber id (personalization). When given: (1) similar-post retrieval "
            "is scoped to that subscriber's own posts, falling back to the global corpus if "
            "they don't have enough yet, and (2) a derived voice profile from their top posts "
            "is injected into every agent's prompt, when enough of their own posts exist."
        ),
    )
    use_voice_profile: bool = Field(
        default=True,
        description=(
            "Whether to derive and apply the subscriber's voice profile when user_id is given. "
            "Has no effect if user_id is not set. Set to false to scope retrieval to the "
            "subscriber without personalizing the agent prompts."
        ),
    )
    seo_mode: Optional[Literal["corpus", "gemini_only"]] = Field(
        default=None,
        description=(
            "SEO/discoverability diagnostic mode. 'corpus' (default) grounds the SEO "
            "worker in your scraped dataset; 'gemini_only' uses the legacy static prompt "
            "for A/B testing."
        ),
    )
    use_google_trends: Optional[bool] = Field(
        default=None,
        description=(
            "Tier 2: include Google Trends timeliness signals (web-wide, not LinkedIn-specific). "
            "Defaults to settings.google_trends_enabled (off unless enabled in env); always off in gemini_only."
        ),
    )
    use_visual_diagnostics: Optional[bool] = Field(
        default=None,
        description=(
            "T7.9+T7.10: run Gemini multimodal visual diagnostics (hierarchy + OCR/copy alignment). "
            "Defaults to settings.visual_diagnostics_enabled (off unless enabled in env). "
            "Requires image_url when enabled; skipped with a note if no image is provided."
        ),
    )
    image_url: Optional[str] = Field(
        default=None,
        description=(
            "Optional draft image URL for visual diagnostics (jpeg/png/webp, max ~5MB). "
            "Ignored when visual diagnostics are off."
        ),
    )


class CritiqueRequest(BaseModel):
    """Independent synthetic-audience critic (T7.11–T7.13). Not part of /evaluate."""

    content: str = Field(
        ...,
        min_length=1,
        description="Draft post text to critique through C-suite, practitioner, and peer lenses.",
    )


class OptimiseRequest(BaseModel):
    """Independent Stage 5 synthesis (T7.14–T7.16). Not part of /evaluate finalize."""

    content: str = Field(
        ...,
        min_length=1,
        description="Draft post text to optimise into maximizer / counter / brand_purist rewrites.",
    )
    primary_objection: Optional[str] = Field(
        default=None,
        description=(
            "Optional C-suite objection (e.g. from /critique). Used by the Strategic Counter "
            "variant. When omitted, a generic executive-skepticism brief is used."
        ),
    )
    baseline_percentile: Optional[float] = Field(
        default=None,
        ge=0,
        le=100,
        description="Optional original-draft predicted percentile for delta display.",
    )
    baseline_total_engagement: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional original-draft predicted total engagement for score fallbacks.",
    )
    user_id: Optional[str] = Field(
        default=None,
        description="Optional subscriber id for neighbor scoping / voice profile.",
    )
    use_voice_profile: bool = Field(
        default=True,
        description="When user_id is set, derive and apply the subscriber voice profile.",
    )


class SubscriberEvidenceBriefRequest(BaseModel):
    """Consent-backed inputs for a Phase 19 concierge evidence baseline."""

    subscriber_id: str = Field(..., min_length=1, max_length=120)
    public_profile_url: str = Field(..., min_length=1, max_length=500)
    profile_authorized: bool = Field(
        ...,
        description="Subscriber confirms authorization to analyze their public LinkedIn profile.",
    )
    role_description: str = Field(..., min_length=2, max_length=1_000)
    primary_niche: str = Field(..., min_length=2, max_length=120)
    sub_niche: str = Field(default="", max_length=240)
    target_audience: str = Field(..., min_length=2, max_length=500)
    objectives: list[str] = Field(default_factory=list, max_length=10)
    locale: str = Field(default="", max_length=160)
    seed_accounts: list[str] = Field(default_factory=list, max_length=20)


class SubscriberEvidenceBriefResponse(BaseModel):
    id: str
    subscriber_id: str
    public_profile_url: str
    profile_authorized: bool
    role_description: str
    primary_niche: str
    sub_niche: str
    target_audience: str
    objectives: list[str]
    locale: str
    seed_accounts: list[str]
    status: Literal["draft", "approved", "paused"]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SubscriberBaselinePlanResponse(BaseModel):
    id: str
    brief_id: str
    provider: Literal["apify"]
    baseline_budget_usd: float = Field(..., ge=0, le=10)
    daily_candidate_limit: int = Field(..., ge=1, le=100)
    source_priorities: list[str]
    proposed_queries: list[str]
    rationale: str
    status: Literal["proposed", "approved", "superseded"]
    created_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None


class SubscriberEvidencePlanResponse(BaseModel):
    brief: SubscriberEvidenceBriefResponse
    plan: SubscriberBaselinePlanResponse


class SubscriberEvidenceReceiptResponse(BaseModel):
    id: str
    subscriber_id: str
    collection_job_id: str
    collected_count: int
    rejected_count: int
    actual_cost_usd: float
    coverage_gaps: list[str]
    next_refresh_at: Optional[datetime] = None
    summary: str
    created_at: Optional[datetime] = None


class SubscriberEvidenceJobResponse(BaseModel):
    id: str
    subscriber_id: str
    brief_id: str
    plan_id: str
    job_kind: Literal["baseline", "daily_refresh"]
    gap_reason: str
    status: Literal["planned", "running", "completed", "failed", "skipped"]
    estimated_cost_usd: float
    actual_cost_usd: float
    candidate_count: int
    accepted_count: int
    rejected_count: int
    recommended_seeds: list[str]
    error_detail: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class SubscriberEvidenceCoverage(BaseModel):
    accepted_count: int
    newest_at: Optional[datetime] = None
    distinct_authors: int
    dominant_author_share: float


class SubscriberEvidenceBudget(BaseModel):
    lifetime_baseline_spent_usd: float
    day_candidates: int
    day_spent_usd: float


class SubscriberEvidenceStatusResponse(BaseModel):
    subscriber_id: str
    brief_status: Literal["draft", "approved", "paused"]
    plan_status: Literal["proposed", "approved", "superseded"]
    plan_id: str
    baseline_budget_usd: float
    daily_candidate_limit: int
    coverage: SubscriberEvidenceCoverage
    budget: SubscriberEvidenceBudget


class SubscriberEvidenceRefreshResponse(BaseModel):
    subscriber_id: str
    action: str
    detail: str
    job_id: Optional[str] = None
    receipt_id: Optional[str] = None


class SubscriberEvidencePostResponse(BaseModel):
    id: str
    post_id: Optional[str] = None
    url: str = ""
    preview: str = ""
    source_type: str = "unknown"
    author_key: str = ""
    created_at: Optional[datetime] = None
    total_engagement: int = 0


class CorpusIngestRequest(BaseModel):
    mode: Literal["embed_and_ingest", "ingest_only"] = Field(
        default="embed_and_ingest",
        description=(
            "embed_and_ingest: load analysed JSONL, embed with Gemini, upsert into pgvector. "
            "ingest_only: pair existing JSONL + .npy and upsert (no new Gemini embed spend)."
        ),
    )
    processed_file: Optional[str] = Field(
        default=None,
        description="Path to analysed JSONL (defaults to latest under data/processed/).",
    )
    embeddings_file: Optional[str] = Field(
        default=None,
        description="Path to .npy embeddings (ingest_only only; defaults to latest).",
    )
    limit: Optional[int] = Field(
        default=None,
        ge=1,
        le=5_000,
        description="Optional cap on posts for embed_and_ingest (cheap test runs).",
    )


class AsyncJobResponse(BaseModel):
    id: str
    kind: str
    status: Literal["queued", "running", "completed", "failed"]
    meta: dict[str, Any] = Field(default_factory=dict)
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class CorpusStatsResponse(BaseModel):
    post_count: int
    benchmarks: Optional[dict[str, Any]] = None
    benchmarks_stale: bool
    benchmarks_path: str


class FeedbackRunRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)


class FeedbackRunResponse(BaseModel):
    claimed: int
    succeeded: int
    failed: int
    dead_lettered: int


class FeedbackCoverageResponse(BaseModel):
    validated: int
    with_feedback: int
    missing_feedback: int


class FeedbackStatsResponse(BaseModel):
    coverage: FeedbackCoverageResponse
    learning: dict[str, Any]
    feedback_enabled: bool
    injection_enabled: bool
    error: Optional[str] = None


class BudgetStatsResponse(BaseModel):
    apify_used_usd: float
    apify_cap_usd: float
    gemini_used_usd: float
    gemini_cap_usd: float
    apify_month_used_usd: float
    apify_month_cap_usd: float
    gemini_month_used_usd: float
    gemini_month_cap_usd: float
    note: str = ""


class AllStatsResponse(BaseModel):
    corpus: CorpusStatsResponse
    feedback: FeedbackStatsResponse
    budget: BudgetStatsResponse
