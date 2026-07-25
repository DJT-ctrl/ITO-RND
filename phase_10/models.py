"""Typed shapes for agentic services (stable UI contracts for T10.2–T10.10)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SeedConfig:
    """Operator bootstrap inputs (editable from Agentic Layer tab)."""

    seed_terms: tuple[str, ...] = ()
    seed_accounts: tuple[str, ...] = ()
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed_terms": list(self.seed_terms),
            "seed_accounts": list(self.seed_accounts),
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class SearchPlan:
    """Source of truth for scrape queries (T10.2 fills weights)."""

    terms: tuple[str, ...] = ()
    seed_accounts: tuple[str, ...] = ()
    weights_by_niche: dict[str, float] = field(default_factory=dict)
    updated_at: str | None = None
    stub: bool = True


@dataclass(frozen=True)
class JobFlags:
    """Enable/disable flags the scheduler (T10.3) will honor."""

    general_refresh: bool = True
    niche_scrape: bool = True
    pro_digest: bool = False
    validation_worker: bool = True
    feedback_worker: bool = True

    def to_dict(self) -> dict[str, bool]:
        return {
            "general_refresh": self.general_refresh,
            "niche_scrape": self.niche_scrape,
            "pro_digest": self.pro_digest,
            "validation_worker": self.validation_worker,
            "feedback_worker": self.feedback_worker,
        }


JOB_FLAG_KEYS: tuple[str, ...] = tuple(JobFlags().to_dict().keys())

JOB_FLAG_LABELS: dict[str, str] = {
    "general_refresh": "General corpus refresh (~3h)",
    "niche_scrape": "Niche scrape (daily)",
    "pro_digest": "Pro workflow digest (daily)",
    "validation_worker": "Validation worker",
    "feedback_worker": "Feedback worker",
}


@dataclass(frozen=True)
class JobRunStatus:
    job_id: str
    label: str
    enabled: bool
    last_run_at: str | None = None
    next_run_at: str | None = None
    last_result: str | None = None


@dataclass(frozen=True)
class ScheduleStatus:
    jobs: tuple[JobRunStatus, ...] = ()
    stub: bool = True


@dataclass(frozen=True)
class BudgetSnapshot:
    """Daily/monthly agentic spend vs configurable caps (T10.9)."""

    apify_used_usd: float = 0.0
    apify_cap_usd: float = 25.0
    gemini_used_usd: float = 0.0
    gemini_cap_usd: float = 10.0
    apify_month_used_usd: float = 0.0
    apify_month_cap_usd: float = 500.0
    gemini_month_used_usd: float = 0.0
    gemini_month_cap_usd: float = 200.0
    stub_caps: bool = False
    note: str = ""


@dataclass(frozen=True)
class BudgetDecision:
    """Result of allow_paid_step (T10.3 budget gate)."""

    allowed: bool
    reason: str | None = None


@dataclass(frozen=True)
class DigestRecord:
    id: str
    created_at: str
    summary: str
    model: str = "gemini-pro"
