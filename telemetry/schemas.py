"""Pydantic schemas for evaluation-cycle telemetry.

Designed for JSON file persistence today and Postgres JSONB storage later
(see telemetry/persist.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

StepStage = Literal["retrieval", "setup", "agent", "variant"]
StepCallType = Literal["llm", "embedding", "db", "compute", "external"]
StepStatus = Literal["ok", "error"]


class StepTelemetry(BaseModel):
    step_id: str
    label: str
    stage: StepStage
    call_type: StepCallType
    model: Optional[str] = None
    status: StepStatus
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    error: Optional[str] = None
    started_at: datetime
    ended_at: datetime


class TelemetryWarning(BaseModel):
    code: str
    message: str
    threshold: float
    actual: float


class RunMetadata(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    user_id: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    agent_model: Optional[str] = None
    variant_strategy: Optional[str] = None
    reembed_variant_neighbors: bool = False
    neighbor_limit: int = 10
    seo_mode: Optional[str] = None
    steps: list[StepTelemetry] = Field(default_factory=list)
    warnings: list[TelemetryWarning] = Field(default_factory=list)
