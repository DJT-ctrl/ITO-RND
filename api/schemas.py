"""Pydantic request/response models for the T2.2 similarity-search endpoint.

This module *is* T2.3 ("API Contract Definition") — FastAPI generates the
full OpenAPI spec (served at /docs and /openapi.json) directly from these
models, so no separate contract document is needed.
"""

from typing import Literal, Optional

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
    hook_type: Optional[str] = None


class SimilarPostsResponse(BaseModel):
    query_content: str
    results: list[SimilarPost]


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
