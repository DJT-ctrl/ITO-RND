"""Pydantic models for the feedback / calibration layer."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

FeedbackDirection = Literal["accurate", "overestimated", "underestimated"]
GenerationMethod = Literal["template", "llm", "human"]


class CalibrationStats(BaseModel):
    """Signed bias from validated predictions (global or per-cluster)."""

    n_validated: int = Field(ge=0)
    mean_delta: float = 0.0
    cluster_id: Optional[str] = None
    source: Literal["cluster", "global", "none"] = "global"


class ClusterStats(BaseModel):
    cluster_id: str
    label: Optional[str] = None
    sample_count: int = 0
    mean_delta: Optional[float] = None
    std_delta: Optional[float] = None


class ClusterAccuracy(BaseModel):
    cluster_id: str
    sample_count: int = 0
    mae: Optional[float] = None
    raw_mae: Optional[float] = None
    calibrated_mae: Optional[float] = None
    pct_within_10: Optional[float] = None


class LearningStatus(BaseModel):
    n_validated: int = 0
    last_cluster_refresh_at: Optional[datetime] = None


class CalibrationResult(BaseModel):
    """Outcome of applying (or skipping) a calibration offset."""

    raw_percentile: float
    calibrated_percentile: float
    mean_delta: float
    n_validated: int
    n_min: int
    applied: bool
    skip_reason: Optional[str] = None


class DeltaSummary(BaseModel):
    predicted_percentile: float
    actual_percentile: float
    prediction_delta: float
    direction: FeedbackDirection


class FeedbackPayload(BaseModel):
    """Structured feedback JSON stored in prediction_feedback.feedback_json."""

    prediction_id: UUID
    delta_summary: DeltaSummary
    what_worked: list[str] = Field(default_factory=list)
    what_missed: list[str] = Field(default_factory=list)
    lessons_for_similar_posts: list[str] = Field(default_factory=list)
    cluster_id: Optional[str] = None


class FeedbackRecord(BaseModel):
    feedback_id: UUID
    prediction_id: UUID
    cluster_id: Optional[str] = None
    feedback_json: FeedbackPayload
    feedback_version: str = "v1"
    generated_at: datetime
    generation_method: GenerationMethod = "template"
    generation_latency_ms: float = Field(default=0.0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)