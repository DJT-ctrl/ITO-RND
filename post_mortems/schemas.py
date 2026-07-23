"""Pydantic models for A1 anomaly post-mortems."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

PostMortemVerdict = Literal[
    "likely_inorganic",
    "plausible_organic_outlier",
    "ambiguous",
    "data_quality",
]

VERDICTS: tuple[str, ...] = (
    "likely_inorganic",
    "plausible_organic_outlier",
    "ambiguous",
    "data_quality",
)


class AnomalyPostRow(BaseModel):
    """Flagged post loaded for post-mortem generation."""

    post_id: str
    content: str
    likes: int
    comments: int
    shares: int
    total_engagement: int
    comment_ratio: Optional[float] = None
    share_ratio: Optional[float] = None
    engagement_percentile: float
    anomaly_reasons: list[str] = Field(default_factory=list)
    topic: Optional[str] = None
    hook_type: Optional[str] = None


class PostMortemLLMOutput(BaseModel):
    verdict: PostMortemVerdict
    summary: str = Field(min_length=1)
    lesson_for_models: str = Field(min_length=1)


class PostMortemRecord(BaseModel):
    post_mortem_id: Optional[UUID] = None
    post_id: str
    machine_reasons: list[str]
    verdict: PostMortemVerdict
    summary: str
    evidence: dict[str, Any]
    lesson_for_models: str
    model: str
    generated_at: Optional[datetime] = None
