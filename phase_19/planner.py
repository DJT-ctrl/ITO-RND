"""Deterministic Release A evidence-plan construction.

The Phase 19 concierge flow must be explainable before it becomes agentic.
This module therefore derives a small, reviewable plan from subscriber inputs;
it makes no provider calls and does not queue collection jobs.
"""

from __future__ import annotations

from urllib.parse import urlparse

from phase_19.models import BaselinePlanProposal, SubscriberEvidenceBrief

BASELINE_BUDGET_USD = 10.0
DAILY_CANDIDATE_LIMIT = 100
BASELINE_SOURCE_PRIORITIES = (
    "subscriber_public_profile",
    "approved_seed_accounts",
    "niche_keyword_queries",
    "shared_niche_corpus",
)
_MAX_PROPOSED_QUERIES = 6


def _unique_nonempty(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        normalized = " ".join(value.split()).strip()
        if normalized and normalized.casefold() not in seen:
            seen.add(normalized.casefold())
            cleaned.append(normalized)
    return tuple(cleaned)


def _validate_public_profile_url(value: str) -> None:
    parsed = urlparse(value.strip())
    hostname = (parsed.hostname or "").casefold()
    is_linkedin_host = hostname == "linkedin.com" or hostname.endswith(".linkedin.com")
    if parsed.scheme != "https" or not is_linkedin_host or not parsed.path.startswith("/in/"):
        raise ValueError("A public HTTPS LinkedIn member-profile URL is required.")


def build_baseline_plan(brief: SubscriberEvidenceBrief) -> BaselinePlanProposal:
    """Return the subscriber-reviewable baseline plan with fixed policy limits."""
    if not brief.profile_authorized:
        raise ValueError("Public-profile authorization is required before proposing a baseline plan.")
    _validate_public_profile_url(brief.public_profile_url)

    niche = " ".join(brief.primary_niche.split()).strip()
    sub_niche = " ".join(brief.sub_niche.split()).strip()
    audience = " ".join(brief.target_audience.split()).strip()
    locale = " ".join(brief.locale.split()).strip()
    if not niche or not audience:
        raise ValueError("A primary niche and target audience are required.")

    niche_phrase = " ".join(part for part in (niche, sub_niche) if part)
    query_candidates = [niche_phrase, f"{niche_phrase} {audience}"]
    if locale:
        query_candidates.append(f"{niche_phrase} {locale}")
    query_candidates.extend(f"{niche_phrase} {objective}" for objective in brief.objectives)
    queries = _unique_nonempty(query_candidates)[:_MAX_PROPOSED_QUERIES]
    rationale = (
        f"Baseline evidence will prioritize the authorized public profile, then approved seeds and "
        f"queries for {niche_phrase} serving {audience}. The plan is capped at ${BASELINE_BUDGET_USD:.2f} "
        f"and records a future maximum of {DAILY_CANDIDATE_LIMIT} candidates per day; it does not collect "
        "data until the subscriber approves it."
    )
    return BaselinePlanProposal(
        provider="apify",
        baseline_budget_usd=BASELINE_BUDGET_USD,
        daily_candidate_limit=DAILY_CANDIDATE_LIMIT,
        source_priorities=BASELINE_SOURCE_PRIORITIES,
        proposed_queries=queries,
        rationale=rationale,
    )