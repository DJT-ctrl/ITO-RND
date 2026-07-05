"""Unit tests for the T3.3 Diagnostic Worker Agents."""

import asyncio

from pydantic_ai.models.test import TestModel

from agents.diagnostics import (
    DiagnosticOutput,
    build_clarity_agent,
    build_diagnostic_agents,
    build_diagnostic_prompt,
    build_seo_agent,
    build_tone_agent,
)
from agents.schemas import EvaluationDeps


def test_build_diagnostic_agents_returns_expected_workers():
    agents = build_diagnostic_agents(TestModel())

    assert set(agents) == {"seo", "clarity", "tone"}
    assert agents["seo"] is not agents["clarity"]
    assert agents["clarity"] is not agents["tone"]


def test_diagnostic_prompts_are_distinct_and_include_draft():
    deps = EvaluationDeps(draft_content="Draft post about hiring a backend engineer.")

    seo_prompt = build_diagnostic_prompt("seo", deps)
    clarity_prompt = build_diagnostic_prompt("clarity", deps)
    tone_prompt = build_diagnostic_prompt("tone", deps)

    assert "Draft post about hiring" in seo_prompt
    assert "keyword" in seo_prompt.lower()
    assert "main point" in clarity_prompt.lower()
    assert "brand persona" in tone_prompt.lower()
    assert len({seo_prompt, clarity_prompt, tone_prompt}) == 3


def test_each_diagnostic_agent_returns_uniform_structured_output_with_test_model():
    deps = EvaluationDeps(draft_content="Draft post about hiring a backend engineer.")
    agents = [
        build_seo_agent(TestModel()),
        build_clarity_agent(TestModel()),
        build_tone_agent(TestModel()),
    ]

    for agent in agents:
        result = asyncio.run(agent.run(deps.draft_content, deps=deps))
        assert isinstance(result.output, DiagnosticOutput)
        assert 0 <= result.output.score <= 10
        assert isinstance(result.output.flaws, list)
        assert isinstance(result.output.advantages, list)
        assert isinstance(result.output.improvements, list)
