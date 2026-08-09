"""Unit tests for Phase 19's deterministic concierge baseline planner."""

import pytest

from phase_19.models import SubscriberEvidenceBrief
from phase_19.planner import (
    BASELINE_BUDGET_USD,
    DAILY_CANDIDATE_LIMIT,
    build_baseline_plan,
)


def _brief(**overrides) -> SubscriberEvidenceBrief:
    values = {
        "subscriber_id": "sports-user-1",
        "public_profile_url": "https://www.linkedin.com/in/sports-user-1/",
        "profile_authorized": True,
        "role_description": "Football academy founder and coach",
        "primary_niche": "sports",
        "sub_niche": "football coaching",
        "target_audience": "academy owners",
        "objectives": ("authority", "sponsorships"),
        "locale": "United Kingdom",
        "seed_accounts": ("https://www.linkedin.com/in/peer-coach/",),
    }
    values.update(overrides)
    return SubscriberEvidenceBrief(**values)


def test_baseline_plan_is_bounded_and_explains_sports_queries() -> None:
    plan = build_baseline_plan(_brief())

    assert plan.provider == "apify"
    assert plan.baseline_budget_usd == BASELINE_BUDGET_USD == 10.0
    assert plan.daily_candidate_limit == DAILY_CANDIDATE_LIMIT == 100
    assert plan.source_priorities[0] == "subscriber_public_profile"
    assert "sports football coaching academy owners" in plan.proposed_queries
    assert "sports football coaching authority" in plan.proposed_queries
    assert "$10.00" in plan.rationale
    assert "does not collect data" in plan.rationale


def test_baseline_plan_requires_profile_authorization() -> None:
    with pytest.raises(ValueError, match="authorization"):
        build_baseline_plan(_brief(profile_authorized=False))


def test_baseline_plan_requires_public_linkedin_member_profile_url() -> None:
    with pytest.raises(ValueError, match="LinkedIn"):
        build_baseline_plan(_brief(public_profile_url="https://example.com/profile"))


def test_baseline_plan_deduplicates_and_limits_queries() -> None:
    plan = build_baseline_plan(
        _brief(
            objectives=("authority", "authority", "", "sponsorships", "community", "recruitment", "leads", "growth"),
            locale="",
        )
    )

    assert len(plan.proposed_queries) <= 6
    assert len(plan.proposed_queries) == len({query.casefold() for query in plan.proposed_queries})