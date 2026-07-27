"""Pydantic request/response models for the public HTTP API (v1 contract).

FastAPI generates the OpenAPI spec from these models (`/docs`, `/openapi.json`).
Human-readable policy and examples live in `docs/api/`. A committed
`openapi.json` snapshot is checked in for contract review and CI (#24).
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from telemetry.schemas import RunMetadata

API_VERSION = "1.0.0"
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
    hook_type: Optional[str] = None


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


class VariantResult(BaseModel):
    variant_text: str
    rationale: str
    strategy_label: str
    predicted_engagement_percentile: float = Field(..., ge=0, le=100)
    predicted_total_engagement: int = Field(..., ge=0)


class EvaluateRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Draft post text to evaluate")
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


class EvaluateResponse(BaseModel):
    """Stable v1 response contract for POST /api/v1/evaluate."""

    draft_content: str
    similar_posts: list[SimilarPost] = Field(default_factory=list)
    voice_profile: Optional[VoiceProfile] = None
    predictor_result: Optional[PredictorResult] = None
    diagnostics: dict[str, DiagnosticResult] = Field(
        default_factory=dict,
        description="Diagnostic worker outputs keyed by check name (e.g. seo, clarity, tone).",
    )
    variants: list[VariantResult] = Field(default_factory=list)
    errors: list[str] = Field(
        default_factory=list,
        description="Non-fatal agent failures collected during the evaluation cycle.",
    )
    run_metadata: Optional[RunMetadata] = None
    query_embedding: Optional[list[float]] = None
    embedding_model_version: Optional[str] = None


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
