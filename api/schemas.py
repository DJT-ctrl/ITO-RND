"""Pydantic request/response models for the T2.2 similarity-search endpoint.

This module *is* T2.3 ("API Contract Definition") — FastAPI generates the
full OpenAPI spec (served at /docs and /openapi.json) directly from these
models, so no separate contract document is needed.
"""

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
