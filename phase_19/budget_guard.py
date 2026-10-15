"""Subscriber budget and policy gates for Phase 19 Release B collection."""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings, load_settings
from phase_10.budget import allow_paid_step
from phase_19 import evidence_store
from phase_19.planner import BASELINE_BUDGET_USD, DAILY_CANDIDATE_LIMIT

JOB_ID = "subscriber_evidence"


@dataclass(frozen=True)
class CollectionGate:
    allowed: bool
    reason: str = ""
    remaining_budget_usd: float = 0.0
    remaining_candidates: int = 0


def evaluate_collection_gate(
    conn,
    *,
    brief: dict,
    plan: dict,
    settings: Settings | None = None,
) -> CollectionGate:
    """Veto unpaid or unapproved collection before any Apify call."""
    settings = settings or load_settings()

    if brief.get("status") == "paused":
        return CollectionGate(allowed=False, reason="brief paused")
    if brief.get("status") != "approved":
        return CollectionGate(allowed=False, reason="brief not approved")
    if plan.get("status") != "approved":
        return CollectionGate(allowed=False, reason="plan not approved")
    if not brief.get("profile_authorized"):
        return CollectionGate(allowed=False, reason="profile not authorized")

    decision = allow_paid_step(JOB_ID, "apify", settings=settings)
    if not decision.allowed:
        return CollectionGate(allowed=False, reason=decision.reason or "global budget denied")

    snap = evidence_store.budget_snapshot(
        conn,
        subscriber_id=brief["subscriber_id"],
        plan_id=plan["id"],
    )
    baseline_cap = float(plan.get("baseline_budget_usd") or BASELINE_BUDGET_USD)
    daily_cap = int(plan.get("daily_candidate_limit") or DAILY_CANDIDATE_LIMIT)
    remaining_budget = max(0.0, baseline_cap - float(snap["lifetime_baseline_spent_usd"]))
    remaining_candidates = max(0, daily_cap - int(snap["day_candidates"]))

    if remaining_budget <= 0:
        return CollectionGate(
            allowed=False,
            reason="subscriber baseline budget exhausted",
            remaining_budget_usd=0.0,
            remaining_candidates=remaining_candidates,
        )
    if remaining_candidates <= 0:
        return CollectionGate(
            allowed=False,
            reason="daily candidate cap reached",
            remaining_budget_usd=remaining_budget,
            remaining_candidates=0,
        )
    return CollectionGate(
        allowed=True,
        remaining_budget_usd=remaining_budget,
        remaining_candidates=remaining_candidates,
    )
