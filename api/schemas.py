"""Pydantic request/response models for the public HTTP API (v1 contract).

FastAPI generates the OpenAPI spec from these models (`/docs`, `/openapi.json`).
Human-readable policy and examples live in `docs/api/`. A committed
`openapi.json` snapshot is checked in for contract review and CI (#24).
"""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from telemetry.schemas import RunMetadata

API_VERSION = "1.1.0"
API_PATH_VERSION = "v1"


class HealthResponse(BaseModel):
    status: Literal["ok"] = Field(..., description="Liveness indicator.")
    api_version: str = Field(
        default=API_PATH_VERSION,
        description="Stable path version for frontend integration (`/api/v1/...`).",
    )


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
    follower_count: Optional[int] = None
    engagement_rate: Optional[float] = None
    audience_adjusted_percentile: Optional[float] = None
    hashtag_count: Optional[int] = None
    word_count: Optional[int] = None
    topic: Optional[str] = None
    niche: Optional[str] = None
    hook_type: Optional[str] = None
    linkedin_url: str = ""
    engagement_anomaly_flag: bool = False
    # Phase 11: age when neighbor engagement was measured (hours since publish).
    posted_at: Optional[datetime] = None
    engagement_age_hours: Optional[float] = None


class SimilarPostsResponse(BaseModel):
    query_content: str
    results: list[SimilarPost]


class VoiceProfile(BaseModel):
    """Derived writing-style summary for a subscriber (cold-start safe)."""

    dominant_hook_type: Optional[str] = None
    dominant_tone: Optional[str] = None
    dominant_writing_style: Optional[str] = None
    avg_word_count: Optional[float] = None
    avg_hashtag_count: Optional[float] = None
    cta_usage_ratio: Optional[float] = None
    sample_size: int = Field(..., ge=1, description="Number of posts used to build the profile.")


class PredictorResult(BaseModel):
    """Engagement prediction for the draft (T3.2 contract)."""

    predicted_engagement_percentile: float = Field(..., ge=0, le=100)
    predicted_total_engagement: int = Field(..., ge=0)
    predicted_likes: Optional[int] = Field(default=None, ge=0)
    predicted_comments: Optional[int] = Field(default=None, ge=0)
    predicted_shares: Optional[int] = Field(default=None, ge=0)
    reasoning: str = Field(..., min_length=1)


class DiagnosticResult(BaseModel):
    """Single diagnostic worker output (T3.3 contract)."""

    score: float = Field(..., ge=0, le=10)
    flaws: list[str] = Field(default_factory=list)
    advantages: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)


class CoachingEvidence(BaseModel):
    """Provenance for cluster-aware coaching guidance."""

    cluster_id: Optional[str] = None
    cluster_label: Optional[str] = None
    sample_count: int = Field(default=0, ge=0)
    validated_feedback_count: int = Field(default=0, ge=0)
    confidence: Literal[
        "cluster_validated", "shape_fallback", "diagnostic_neighbor"
    ]
    age_bucket: Optional[str] = None
    summary: str = Field(..., min_length=1)


class DetailedCoachingAction(BaseModel):
    """The single highest-priority, draft-specific improvement."""

    priority: Literal["high"] = "high"
    title: str = Field(..., min_length=3, max_length=120)
    draft_anchor: str = Field(..., min_length=3, max_length=300)
    diagnosis: str = Field(..., min_length=20, max_length=600)
    edit_instruction: str = Field(..., min_length=20, max_length=600)
    example_replacement: str = Field(..., min_length=10, max_length=800)
    expected_effect: str = Field(..., min_length=20, max_length=500)
    evidence_refs: list[str] = Field(min_length=1, max_length=5)


class CoachingAction(BaseModel):
    """A lower-priority, distinct supporting improvement."""

    priority: Literal["medium", "low"]
    title: str = Field(..., min_length=3, max_length=120)
    recommendation: str = Field(..., min_length=20, max_length=600)
    rationale: str = Field(..., min_length=20, max_length=500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=5)


class ClusterCoachingResult(BaseModel):
    """Evidence-grounded, draft-specific coaching shown before diagnostics."""

    status: Literal["ready", "unavailable"]
    summary: str = Field(..., min_length=1, max_length=800)
    evidence: CoachingEvidence
    primary_action: Optional[DetailedCoachingAction] = None
    supporting_actions: list[CoachingAction] = Field(default_factory=list, max_length=2)


class VariantResult(BaseModel):
    variant_text: str
    rationale: str
    strategy_label: str
    predicted_engagement_percentile: float = Field(..., ge=0, le=100)
    predicted_total_engagement: int = Field(..., ge=0)


class CrossReferencePost(BaseModel):
    """One close historical post that outperformed the draft baseline."""

    post: SimilarPost
    comparison_metric: Literal[
        "audience_adjusted_percentile", "engagement_percentile"
    ]
    effective_percentile: float = Field(..., ge=0, le=100)
    percentile_uplift: float = Field(..., gt=0)
    selection_score: float = Field(..., ge=0)
    selection_reasons: list[str] = Field(default_factory=list)
    observed_strengths: list[str] = Field(default_factory=list)
    suggested_adaptation: Optional[str] = None


class CrossReferenceResult(BaseModel):
    """Curated, observational evidence from stronger close historical posts."""

    status: Literal["ready", "insufficient_evidence", "analysis_unavailable"]
    selection_method: str = "global_semantic_performance_v1"
    baseline_percentile: Optional[float] = Field(default=None, ge=0, le=100)
    baseline_method: Optional[str] = None
    candidates_evaluated: int = Field(default=0, ge=0)
    eligible_candidates: int = Field(default=0, ge=0)
    references: list[CrossReferencePost] = Field(default_factory=list)
    overall_feedback: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


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
            "shifts topic/angle, at the cost of up to 3 extra Gemini embed calls and 6 extra "
            "DB queries for scoped scoring neighbors plus global comparison candidates). "
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
            "Opt-in visual diagnostics when an image_url is provided. "
            "Defaults to settings.visual_diagnostics_enabled (off unless enabled in env). "
        ),
    )
    image_url: Optional[str] = Field(
        default=None,
        description="Optional image URL for visual diagnostics (ignored unless visual diagnostics are enabled).",
    )



class CritiqueRequest(BaseModel):
    """Independent synthetic-audience critic (T7.11–T7.13)."""

    content: str = Field(..., min_length=1, description="Draft post text to critique")


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

class EvaluateResponse(BaseModel):
    """Stable v1 response contract for POST /api/v1/evaluate."""

    draft_content: str
    similar_posts: list[SimilarPost] = Field(default_factory=list)
    voice_profile: Optional[VoiceProfile] = None
    predictor_result: Optional[PredictorResult] = None
    cluster_coaching: Optional[ClusterCoachingResult] = None
    diagnostics: dict[str, DiagnosticResult] = Field(
        default_factory=dict,
        description="Diagnostic worker outputs keyed by check name (e.g. seo, clarity, tone).",
    )
    variants: list[VariantResult] = Field(default_factory=list)
    cross_references: Optional[CrossReferenceResult] = None
    errors: list[str] = Field(
        default_factory=list,
        description="Non-fatal agent failures collected during the evaluation cycle.",
    )
    run_metadata: Optional[RunMetadata] = None
    query_embedding: Optional[list[float]] = None
    embedding_model_version: Optional[str] = None
    visual_diagnostics_requested: bool = False


class AgentDescriptor(BaseModel):
    """Agent exposed by backend for UI discovery and status mapping."""

    id: str = Field(..., description="Stable machine id, e.g. predictor or seo.")
    name: str = Field(..., description="Human-readable label for UI display.")
    kind: Literal["predictor", "diagnostic", "variant", "system"] = Field(
        ..., description="Agent category for iconography/grouping."
    )
    stage: Literal["setup", "evaluation", "optimization", "reporting", "monitoring"] = Field(
        ..., description="Primary workflow stage where the agent executes."
    )
    description: str = Field(..., description="Short plain-language purpose.")


class AgentCatalogResponse(BaseModel):
    """Stable v1 contract for GET /api/v1/agents."""

    agents: list[AgentDescriptor] = Field(default_factory=list)


class ApiErrorResponse(BaseModel):
    """Documented error envelope for frontend handling (runtime wiring in #7)."""

    code: str = Field(..., description="Machine-readable error code (e.g. EMBED_FAILED, AGENT_UNAVAILABLE).")
    message: str = Field(..., description="Human-readable summary safe to show in the UI.")
    retryable: bool = Field(..., description="Whether the client should offer a retry action.")
    details: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional structured context (field names, provider hint, etc.).",
    )


class ValidationErrorItem(BaseModel):
    loc: list[str | int] = Field(..., description="JSON path to the invalid field.")
    msg: str
    type: str


class ValidationErrorResponse(BaseModel):
    """FastAPI/Pydantic request validation failure (HTTP 422)."""

    detail: list[ValidationErrorItem]
