"""Tests for deterministic stronger-post cross-reference selection."""

from agents.cross_reference import CrossReferencePolicy, select_cross_references
from api.schemas import SimilarPost


def make_post(
    post_id: str,
    *,
    percentile: float = 80.0,
    adjusted_percentile: float | None = None,
    distance: float = 0.10,
    content: str = "A sufficiently detailed historical LinkedIn post for meaningful comparison context.",
    anomaly: bool = False,
    niche: str | None = None,
    age_hours: float | None = None,
) -> SimilarPost:
    return SimilarPost(
        post_id=post_id,
        content=content,
        likes=20,
        comments=4,
        shares=2,
        total_engagement=26,
        engagement_percentile=percentile,
        engagement_zscore=1.0,
        cosine_distance=distance,
        audience_adjusted_percentile=adjusted_percentile,
        engagement_anomaly_flag=anomaly,
        niche=niche,
        engagement_age_hours=age_hours,
        linkedin_url=f"https://www.linkedin.com/posts/{post_id}",
    )


def test_select_cross_references_uses_adjusted_metric_when_present():
    adjusted = make_post("adjusted", percentile=96.0, adjusted_percentile=84.0, distance=0.05)
    raw = make_post("raw", percentile=88.0, distance=0.06)

    result = select_cross_references(
        [adjusted, raw],
        {"percentile": 70.0, "method": "audience_adjusted"},
    )

    by_id = {item.post.post_id: item for item in result.references}
    assert result.status == "ready"
    assert by_id["adjusted"].comparison_metric == "audience_adjusted_percentile"
    assert by_id["adjusted"].effective_percentile == 84.0
    assert by_id["raw"].comparison_metric == "engagement_percentile"
    assert by_id["adjusted"].post.linkedin_url.endswith("adjusted")


def test_selector_excludes_anomalous_distant_and_weaker_candidates():
    qualified = make_post("qualified", percentile=83.0, distance=0.08)
    anomalous = make_post("anomalous", percentile=99.0, distance=0.01, anomaly=True)
    distant = make_post("distant", percentile=99.0, distance=0.30)
    weaker = make_post("weaker", percentile=69.0, distance=0.01)

    result = select_cross_references(
        [qualified, anomalous, distant, weaker],
        {"percentile": 70.0},
    )

    assert [item.post.post_id for item in result.references] == ["qualified"]
    assert result.candidates_evaluated == 4
    assert result.eligible_candidates == 1


def test_selector_returns_explicit_empty_evidence_state():
    result = select_cross_references(
        [make_post("close-but-not-better", percentile=76.0, distance=0.04)],
        {"percentile": 70.0},
    )

    assert result.status == "insufficient_evidence"
    assert result.references == []
    assert result.overall_feedback == []
    assert "No sufficiently close" in result.caveats[0]


def test_selector_prefers_matching_niche_and_age_as_tie_breakers():
    matching = make_post("matching", percentile=82.0, distance=0.10, niche="ai_tech", age_hours=24)
    generic = make_post("generic", percentile=82.0, distance=0.10, niche="other", age_hours=96)

    result = select_cross_references(
        [generic, matching],
        {"percentile": 70.0},
        policy=CrossReferencePolicy(min_percentile_uplift=10.0),
        prefer_niche="ai_tech",
        prefer_age_hours=24,
    )

    assert [item.post.post_id for item in result.references] == ["matching", "generic"]
    assert "Matches the requested niche" in result.references[0].selection_reasons[-2]
    assert "engagement-age bucket" in result.references[0].selection_reasons[-1]
