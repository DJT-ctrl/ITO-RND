"""Unit tests for T7.11–T7.13 combined synthetic audience critic."""

import asyncio

from pydantic_ai.models.test import TestModel

from agents.audience_critic import (
    AudienceCriticOutput,
    build_audience_critic_agent,
    build_audience_critic_system_prompt,
    build_audience_critic_user_message,
    run_audience_critic,
)


def test_system_prompt_covers_three_lenses():
    prompt = build_audience_critic_system_prompt()
    assert "c_suite" in prompt
    assert "practitioner" in prompt
    assert "peer" in prompt
    assert "independent" in prompt.lower() or "NOT part of" in prompt


def test_system_prompt_can_include_draft():
    prompt = build_audience_critic_system_prompt("ROI without metrics is fluff.")
    assert "ROI without metrics" in prompt
    assert "<post_content>" in prompt


def test_user_message_wraps_draft():
    msg = build_audience_critic_user_message("Ship the feature this week.")
    assert "<post_content>" in msg
    assert "Ship the feature this week." in msg


def test_audience_critic_schema_round_trip():
    payload = AudienceCriticOutput.model_validate(
        {
            "overall_verdict": "Thin on ROI; light on tactics.",
            "score": 4.5,
            "c_suite": {
                "reaction": "Skeptical",
                "primary_objection": "No quantified outcome.",
                "roi_notes": "Sounds like a pitch deck slide.",
            },
            "practitioner": {
                "reaction": "Unclear next step",
                "perceived_value": "Motivational, not operational.",
                "tactical_gaps": "Missing checklist / owners.",
            },
            "peer": {
                "reaction": "Heard this before",
                "credibility_check": "Generic thought-leadership.",
                "originality_notes": "Overlaps common LinkedIn tropes.",
            },
        }
    )
    assert payload.c_suite.primary_objection.startswith("No quantified")
    assert payload.practitioner.perceived_value
    assert payload.peer.credibility_check
    assert 0 <= payload.score <= 10


def test_audience_critic_agent_returns_structured_output_with_test_model():
    agent = build_audience_critic_agent(TestModel())
    result = asyncio.run(
        run_audience_critic(
            "We help enterprises unlock synergy and drive digital transformation.",
            agent=agent,
        )
    )
    assert isinstance(result, AudienceCriticOutput)
    assert 0 <= result.score <= 10
    assert result.c_suite.reaction
    assert result.practitioner.reaction
    assert result.peer.reaction
