"""Pydantic request/response models for the T2.2 similarity-search endpoint.

This module *is* T2.3 ("API Contract Definition") — FastAPI generates the
full OpenAPI spec (served at /docs and /openapi.json) directly from these
models, so no separate contract document is needed.
"""

from typing import Literal

from pydantic import BaseModel, Field


class SimilarPostsRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Draft post text to find similar posts for")
    limit: int = Field(default=10, ge=1, le=50)


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
