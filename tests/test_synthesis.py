"""Unit tests for T7.14–T7.16 synthesis optimisation package."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic_ai.models.test import TestModel

from agents.synthesis.generator import generate_synthesis_drafts
from agents.synthesis.prompts import build_synthesis_system_prompt
from agents.synthesis.recommend import recommend_synthesis_variant
from agents.synthesis.schemas import (
    SynthesisDraftItem,
    SynthesisDraftSet,
    SynthesisResult,
    SynthesisVariant,
)
from agents.synthesis.runner import run_synthesis
from config.settings import Settings


def _settings() -> Settings:
    return Settings(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="test",
        raw_data_dir="data/raw",
        default_search_limit=20,
        database_url="",
    )


def test_system_prompt_covers_three_agents():
    prompt = build_synthesis_system_prompt(primary_objection="No ROI proof.")
    assert "maximizer" in prompt
    assert "counter" in prompt
    assert "brand_purist" in prompt
    assert "No ROI proof" in prompt


def test_recommend_picks_highest_percentile():
    variants = [
        SynthesisVariant(
            agent_id="maximizer",
            variant_name="Algorithmic Maximizer",
            optimized_text="a",
            rationale="r",
            predicted_engagement_percentile=70,
            predicted_total_engagement=70,
        ),
        SynthesisVariant(
            agent_id="counter",
            variant_name="Strategic Counter",
            optimized_text="b",
            rationale="r",
            predicted_engagement_percentile=50,
            predicted_total_engagement=50,
        ),
        SynthesisVariant(
            agent_id="brand_purist",
            variant_name="Brand Purist",
            optimized_text="c",
            rationale="r",
            predicted_engagement_percentile=60,
            predicted_total_engagement=60,
        ),
    ]
    rec = recommend_synthesis_variant(variants)
    assert rec.agent_id == "maximizer"


def test_recommend_soft_prefers_counter_when_close_and_objection():
    variants = [
        SynthesisVariant(
            agent_id="maximizer",
            variant_name="Algorithmic Maximizer",
            optimized_text="a",
            rationale="r",
            predicted_engagement_percentile=72,
            predicted_total_engagement=72,
        ),
        SynthesisVariant(
            agent_id="counter",
            variant_name="Strategic Counter",
            optimized_text="b",
            rationale="r",
            predicted_engagement_percentile=70,
            predicted_total_engagement=70,
        ),
        SynthesisVariant(
            agent_id="brand_purist",
            variant_name="Brand Purist",
            optimized_text="c",
            rationale="r",
            predicted_engagement_percentile=55,
            predicted_total_engagement=55,
        ),
    ]
    rec = recommend_synthesis_variant(
        variants, critic_objection_used="Missing quantified ROI."
    )
    assert rec.agent_id == "counter"
    assert "C-suite" in rec.reason or "objection" in rec.reason.lower()


def test_generate_synthesis_drafts_with_test_model():
    drafts = asyncio.run(
        generate_synthesis_drafts(
            "Excited to announce our launch!",
            model=TestModel(),
        )
    )
    assert isinstance(drafts, SynthesisDraftSet)
    assert drafts.maximizer.agent_id == "maximizer"
    assert drafts.counter.agent_id == "counter"
    assert drafts.brand_purist.agent_id == "brand_purist"


@patch("agents.synthesis.runner.score_synthesis_drafts")
@patch("agents.synthesis.runner.generate_synthesis_drafts")
@patch("agents.synthesis.runner.fetch_neighbors_for_text")
def test_run_synthesis_orchestrates_generate_score_recommend(
    mock_fetch, mock_generate, mock_score
):
    mock_fetch.return_value = []
    mock_generate.return_value = SynthesisDraftSet(
        maximizer=SynthesisDraftItem(
            agent_id="maximizer", optimized_text="max", rationale="r1"
        ),
        counter=SynthesisDraftItem(
            agent_id="counter", optimized_text="ctr", rationale="r2"
        ),
        brand_purist=SynthesisDraftItem(
            agent_id="brand_purist", optimized_text="pur", rationale="r3"
        ),
    )

    async def _score(drafts, **kwargs):
        scored = [
            SynthesisVariant(
                agent_id=d.agent_id,
                variant_name=d.agent_id,
                optimized_text=d.optimized_text,
                rationale=d.rationale,
                predicted_engagement_percentile=40.0 + i * 10,
                predicted_total_engagement=40 + i * 10,
                delta_percentile=5.0,
            )
            for i, d in enumerate(drafts)
        ]
        return scored, []

    mock_score.side_effect = _score

    predictor = MagicMock()
    result = asyncio.run(
        run_synthesis(
            "Draft post about ROI.",
            _settings(),
            primary_objection="No numbers.",
            baseline_percentile=50.0,
            predictor_agent=predictor,
            model=TestModel(),
        )
    )
    assert isinstance(result, SynthesisResult)
    assert len(result.variants) == 3
    assert result.critic_objection_used == "No numbers."
    assert result.recommendation.agent_id in {
        "maximizer",
        "counter",
        "brand_purist",
    }
    mock_generate.assert_awaited()
    mock_score.assert_awaited()
