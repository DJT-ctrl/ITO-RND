"""Pydantic models for the prediction validation pipeline."""

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

PredictionStatus = Literal["scheduled", "validating", "validated", "failed", "skipped"]
CalibrationSource = Literal["cluster", "global", "none"]


class PredictionTelemetry(BaseModel):
    """Explain every learning decision that affected a prediction."""

    raw_percentile: Optional[float] = None
    calibrated_percentile: Optional[float] = None
    calibration_enabled: bool = False
    calibration_applied: bool = False
    calibration_skip_reason: Optional[str] = None
    mean_delta: Optional[float] = None
    n_validated: Optional[int] = None
    calibration_source: CalibrationSource = "none"
    cluster_id: Optional[str] = None
    feedback_injection_enabled: bool = False
    feedback_injected: bool = False
    feedback_count: int = Field(default=0, ge=0)
    feedback_version: Optional[str] = None
    feedback_chars: int = Field(default=0, ge=0)
    feedback_token_estimate: int = Field(default=0, ge=0)


class EngagementForecast(BaseModel):
    predicted_likes: int = Field(ge=0)
    predicted_comments: int = Field(ge=0)
    predicted_shares: int = Field(ge=0)
    predicted_total_engagement: int = Field(ge=0)


class PredictionRecord(BaseModel):
    prediction_id: UUID
    linkedin_post_id: str
    linkedin_url: str
    author_public_id: str = ""
    content: str
    posted_at: datetime

    predicted_engagement_percentile: float
    predicted_total_engagement: Optional[int] = None
    predicted_likes: Optional[int] = None
    predicted_comments: Optional[int] = None
    predicted_shares: Optional[int] = None
    baseline_likes: Optional[int] = None
    baseline_comments: Optional[int] = None
    baseline_shares: Optional[int] = None
    baseline_total_engagement: Optional[int] = None
    prediction_method: Optional[str] = None
    neighbor_count: Optional[int] = None
    telemetry: PredictionTelemetry = Field(default_factory=PredictionTelemetry)

    status: PredictionStatus = "scheduled"
    validation_due_at: datetime
    validated_at: Optional[datetime] = None

    actual_likes: Optional[int] = None
    actual_comments: Optional[int] = None
    actual_shares: Optional[int] = None
    actual_total_engagement: Optional[int] = None
    actual_engagement_percentile: Optional[float] = None
    prediction_delta: Optional[float] = None
    accuracy_score: Optional[float] = None
    likes_delta: Optional[float] = None
    comments_delta: Optional[float] = None
    shares_delta: Optional[float] = None
    total_engagement_delta: Optional[float] = None
    validation_error: Optional[str] = None

    created_at: Optional[datetime] = None


class NewPrediction(BaseModel):
    linkedin_post_id: str
    linkedin_url: str
    author_public_id: str = ""
    content: str
    posted_at: datetime
    predicted_engagement_percentile: float
    predicted_total_engagement: Optional[int] = None
    predicted_likes: Optional[int] = None
    predicted_comments: Optional[int] = None
    predicted_shares: Optional[int] = None
    baseline_likes: Optional[int] = None
    baseline_comments: Optional[int] = None
    baseline_shares: Optional[int] = None
    baseline_total_engagement: Optional[int] = None
    prediction_method: Optional[str] = None
    neighbor_count: Optional[int] = None
    telemetry: PredictionTelemetry = Field(default_factory=PredictionTelemetry)
    validation_due_at: datetime


class EngagementActuals(BaseModel):
    likes: int = Field(ge=0)
    comments: int = Field(ge=0)
    shares: int = Field(ge=0)
    total_engagement: int = Field(ge=0)


class ValidationScores(BaseModel):
    actual_engagement_percentile: float
    prediction_delta: float
    accuracy_score: float
    corpus_sample_size: int
    likes_delta: float
    comments_delta: float
    shares_delta: float
    total_engagement_delta: float


class ValidationResult(BaseModel):
    prediction_id: UUID
    status: PredictionStatus
    actuals: Optional[EngagementActuals] = None
    scores: Optional[ValidationScores] = None
    error: Optional[str] = None


class ValidationBatchResult(BaseModel):
    processed: int = 0
    validated: int = 0
    failed: int = 0
    results: list[ValidationResult] = Field(default_factory=list)


class CollectPredictResult(BaseModel):
    scraped: int = 0
    predicted: int = 0
    skipped: int = 0
    predictions: list[PredictionRecord] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class CollectedPost(BaseModel):
    linkedin_post_id: str
    linkedin_url: str
    author_public_id: str = ""
    content: str
    posted_at: datetime
    follower_count: Optional[int] = None
    likes: int = 0
    comments: int = 0
    shares: int = 0
    total_engagement: int = 0


class AccuracyAggregates(BaseModel):
    total_validated: int = 0
    mean_absolute_error: Optional[float] = None
    raw_mean_absolute_error: Optional[float] = None
    calibrated_mean_absolute_error: Optional[float] = None
    median_absolute_error: Optional[float] = None
    pct_within_10: Optional[float] = None
    raw_pct_within_10: Optional[float] = None
    calibrated_pct_within_10: Optional[float] = None
    mean_accuracy_score: Optional[float] = None
    mae_likes: Optional[float] = None
    mae_comments: Optional[float] = None
    mae_shares: Optional[float] = None
    mae_total_engagement: Optional[float] = None
    pct_total_within_20pct: Optional[float] = None
    time_series: list[dict[str, Any]] = Field(default_factory=list)
    method_time_series: list[dict[str, Any]] = Field(default_factory=list)
