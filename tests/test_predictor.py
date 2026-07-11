"""Unit tests for the T3.2 Predictor Agent."""

import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
from pydantic_ai.models.test import TestModel

from agents.diagnostics import build_diagnostic_agents
from agents.orchestrator import run_evaluation_cycle
from agents.predictor import (
    PredictorOutput,
    apply_deterministic_prediction,
    build_predictor_agent,
    build_predictor_prompt,
)
from agents.prompt_safety import PROMPT_DATA_PREAMBLE
from agents.schemas import EvaluationDeps
from api.schemas import SimilarPost
from config.settings import Settings


def fake_post(post_id: str = "1") -> SimilarPost:
    return SimilarPost(
        post_id=post_id,
        content="Strong launch post with a clear hook and direct CTA.",
        likes=20,
        comments=4,
        shares=2,
        total_engagement=26,
        engagement_percentile=82.0,
        engagement_zscore=1.1,
        cosine_distance=0.04,
    )


def fake_row(post_id: str = "1") -> dict:
    return fake_post(post_id).model_dump()


def fake_settings() -> Settings:
    return Settings(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="fake-key",
        raw_data_dir="data/raw",
        default_search_limit=20,
        database_url="postgresql://fake/fake",
    )


def _patch_neighbor_fetch(rows: list[dict]):
    return (
        patch("agents.orchestrator.embed_query", return_value=np.zeros(3072, dtype=np.float32)),
        patch("agents.orchestrator.find_similar", return_value=rows),
        patch("agents.orchestrator.get_connection", return_value=MagicMock()),
        patch("agents.orchestrator.register_vector"),
    )


def test_predictor_prompt_includes_neighbor_context():
    deps = EvaluationDeps(
        draft_content="Draft post about a product launch.",
        similar_posts=[fake_post("abc")],
    )

    prompt = build_predictor_prompt(deps)

    assert PROMPT_DATA_PREAMBLE in prompt
    assert "<post_content>" in prompt
    assert "Draft post about a product launch" in prompt
    assert "Neighbor 1" in prompt
    assert "Total engagement: 26" in prompt
    assert "Engagement percentile: 82.0" in prompt
    assert "Strong launch post" in prompt


def test_predictor_prompt_handles_zero_neighbors():
    prompt = build_predictor_prompt(EvaluationDeps(draft_content="Draft without neighbors."))

    assert "Draft without neighbors" in prompt
    assert "No comparable historical posts were found" in prompt


def test_predictor_prompt_omits_audience_adjusted_lines_when_absent():
    """A neighbor with no follower-normalized data (the default, non-
    enriched path) must produce a prompt with none of the optional lines —
    byte-identical behavior to before T6 Point 1 existed."""
    deps = EvaluationDeps(draft_content="Draft post.", similar_posts=[fake_post("abc")])

    prompt = build_predictor_prompt(deps)

    assert "Author follower count" not in prompt
    assert "Engagement rate" not in prompt
    assert "Audience-adjusted percentile" not in prompt


def test_predictor_prompt_includes_audience_adjusted_lines_when_present():
    post = SimilarPost(
        post_id="abc",
        content="Strong launch post with a clear hook and direct CTA.",
        likes=20,
        comments=4,
        shares=2,
        total_engagement=26,
        engagement_percentile=82.0,
        engagement_zscore=1.1,
        cosine_distance=0.04,
        follower_count=500,
        engagement_rate=0.052,
        audience_adjusted_percentile=91.0,
    )
    deps = EvaluationDeps(
        draft_content="Draft post.",
        similar_posts=[post],
        neighbor_prediction={
            "percentile": 88.5,
            "total_engagement_estimate": 40,
            "method": "audience_adjusted",
            "coverage": 1,
            "neighbor_count": 1,
        },
    )

    prompt = build_predictor_prompt(deps)

    assert "Author follower count: 500" in prompt
    assert "Engagement rate (engagement/follower): 0.0520" in prompt
    assert "Audience-adjusted percentile: 91.0" in prompt
    assert "Deterministic prediction" in prompt
    assert "audience-adjusted (reach-normalized)" in prompt
    assert "88.5" in prompt


def test_predictor_prompt_prioritizes_audience_adjusted_reasoning_when_method_is_adjusted():
    post = SimilarPost(
        post_id="abc",
        content="Strong launch post.",
        likes=20,
        comments=4,
        shares=2,
        total_engagement=26,
        engagement_percentile=82.0,
        engagement_zscore=1.1,
        cosine_distance=0.04,
        audience_adjusted_percentile=91.0,
        follower_count=500,
        engagement_rate=0.052,
    )
    deps = EvaluationDeps(
        draft_content="Draft post.",
        similar_posts=[post],
        neighbor_prediction={
            "percentile": 88.5,
            "total_engagement_estimate": 40,
            "method": "audience_adjusted",
            "coverage": 1,
            "neighbor_count": 1,
        },
    )

    prompt = build_predictor_prompt(deps)

    assert "audience-adjusted percentile is plausible" in prompt
    assert "raw view/like totals" in prompt


def test_predictor_prompt_includes_draft_author_follower_context():
    deps = EvaluationDeps(
        draft_content="Draft post.",
        similar_posts=[fake_post("abc")],
        draft_follower_count=1200,
        neighbor_prediction={
            "percentile": 70.0,
            "total_engagement_estimate": 50,
            "method": "raw_fallback",
            "coverage": 0,
            "neighbor_count": 1,
        },
    )

    prompt = build_predictor_prompt(deps)

    assert "Draft author reach context" in prompt
    assert "1,200 followers" in prompt


def test_apply_deterministic_prediction_overrides_llm_numbers():
    output = PredictorOutput(
        predicted_engagement_percentile=99.0,
        predicted_total_engagement=999,
        reasoning="Because neighbors look strong.",
    )
    corrected = apply_deterministic_prediction(
        output,
        {
            "percentile": 72.5,
            "total_engagement_estimate": 48,
            "method": "audience_adjusted",
            "coverage": 2,
            "neighbor_count": 2,
        },
    )
    assert corrected.predicted_engagement_percentile == 72.5
    assert corrected.predicted_total_engagement == 48
    assert corrected.reasoning == "Because neighbors look strong."


def test_predictor_prompt_includes_voice_profile_when_present():
    deps = EvaluationDeps(
        draft_content="Draft post about a product launch.",
        voice_profile={
            "dominant_hook_type": "question",
            "dominant_tone": "casual",
            "dominant_writing_style": "story",
            "avg_word_count": 120.0,
            "avg_hashtag_count": 3.0,
            "cta_usage_ratio": 0.8,
            "sample_size": 7,
        },
    )

    prompt = build_predictor_prompt(deps)

    assert "subscriber's own writing style" in prompt
    assert "question" in prompt
    assert "casual" in prompt


def test_predictor_prompt_omits_voice_section_when_absent():
    prompt = build_predictor_prompt(EvaluationDeps(draft_content="Draft without a voice profile."))

    assert "subscriber's own writing style" not in prompt


def test_predictor_agent_returns_structured_output_with_test_model():
    agent = build_predictor_agent(TestModel())

    result = asyncio.run(
        agent.run(
            "Draft post about a product launch.",
            deps=EvaluationDeps(draft_content="Draft post about a product launch.", similar_posts=[fake_post()]),
        )
    )

    assert isinstance(result.output, PredictorOutput)
    assert 0 <= result.output.predicted_engagement_percentile <= 100
    assert result.output.predicted_total_engagement >= 0
    assert result.output.reasoning


def test_predictor_and_diagnostics_integrate_with_orchestrator():
    predictor = build_predictor_agent(TestModel())
    diagnostics = build_diagnostic_agents(TestModel())
    p1, p2, p3, p4 = _patch_neighbor_fetch([fake_row("1"), fake_row("2")])

    with p1, p2, p3, p4:
        state = asyncio.run(
            run_evaluation_cycle(
                "Draft post about a product launch.",
                fake_settings(),
                predictor=predictor,
                diagnostics=diagnostics,
            )
        )

    assert len(state.similar_posts) == 2
    assert state.predictor_result is not None
    assert set(state.predictor_result) == {
        "predicted_engagement_percentile",
        "predicted_total_engagement",
        "reasoning",
    }
    assert set(state.diagnostics) == {"seo", "clarity", "tone"}
    for output in state.diagnostics.values():
        assert set(output) == {"score", "flaws", "advantages", "improvements"}
    assert state.errors == []
