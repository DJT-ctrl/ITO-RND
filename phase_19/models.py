"""Domain models for Phase 19's concierge evidence-baseline workflow."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubscriberEvidenceBrief:
    subscriber_id: str
    public_profile_url: str
    profile_authorized: bool
    role_description: str
    primary_niche: str
    sub_niche: str
    target_audience: str
    objectives: tuple[str, ...] = ()
    locale: str = ""
    seed_accounts: tuple[str, ...] = ()


@dataclass(frozen=True)
class BaselinePlanProposal:
    provider: str
    baseline_budget_usd: float
    daily_candidate_limit: int
    source_priorities: tuple[str, ...]
    proposed_queries: tuple[str, ...]
    rationale: str