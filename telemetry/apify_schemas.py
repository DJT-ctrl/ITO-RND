"""Apify actor-run cost telemetry schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

ApifyScraperKind = Literal["linkedin_posts", "linkedin_profiles"]


class ApifyRunRecord(BaseModel):
    """One Apify actor run with USD cost from usageTotalUsd."""

    schema_version: str = "1.0"
    run_id: str
    actor_id: str
    scraper: ApifyScraperKind
    status: str
    cost_usd: float = 0.0
    compute_units: Optional[float] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    item_count: int = 0
    context: Optional[str] = None
    recorded_at: datetime


class ApifyCostSummary(BaseModel):
    """Aggregated Apify spend over a set of runs."""

    run_count: int = 0
    total_cost_usd: float = 0.0
    post_search_cost_usd: float = 0.0
    profile_scrape_cost_usd: float = 0.0
    runs: list[ApifyRunRecord] = Field(default_factory=list)
