"""Pydantic models for offline detailed feedback on stored posts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

ReviewStatus = Literal["pending", "approved", "rejected"]

REVIEW_STATUSES: tuple[str, ...] = ("pending", "approved", "rejected")

NEIGHBOR_LIMIT = 5


class EligiblePost(BaseModel):
    """Clean, labelled post loaded for feedback generation."""

    post_id: str
    content: str
    engagement_percentile: float
    engagement_zscore: float
    word_count: int
    hashtag_count: int = 0
    has_media: bool = False
    hook_type: Optional[str] = None
    tone: Optional[str] = None
    topic: Optional[str] = None
    has_explicit_cta: Optional[bool] = None
    writing_style: Optional[str] = None
    gemini_labels: dict[str, Any] = Field(default_factory=dict)
    huggingface_labels: dict[str, Any] = Field(default_factory=dict)


class PostFeedbackLLMOutput(BaseModel):
    summary: str = Field(min_length=1)
    what_worked: list[str] = Field(min_length=1)
    what_to_change: list[str] = Field(min_length=1)


class PostFeedbackRecord(BaseModel):
    post_feedback_id: Optional[UUID] = None
    post_id: str
    summary: str
    what_worked: list[str]
    what_to_change: list[str]
    neighbor_notes: list[dict[str, Any]] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    review_status: ReviewStatus = "pending"
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    generated_at: Optional[datetime] = None
