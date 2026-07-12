"""Unit tests for the T3.3 Diagnostic Worker Agents."""

import asyncio

from pydantic_ai.models.test import TestModel

from agents.diagnostics import (
    DiagnosticOutput,
    build_clarity_agent,
    build_diagnostic_agents,
    build_diagnostic_prompt,
    build_seo_agent,
    build_seo_prompt,
    build_tone_agent,
)
from agents.prompt_safety import PROMPT_DATA_PREAMBLE
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
    assert PROMPT_DATA_PREAMBLE in seo_prompt
    assert "<post_content>" in seo_prompt
    assert "keyword" in seo_prompt.lower()
    assert "main point" in clarity_prompt.lower()
    assert "brand persona" in tone_prompt.lower()
    assert len({seo_prompt, clarity_prompt, tone_prompt}) == 3


def test_diagnostic_prompt_includes_voice_profile_when_present():
    deps = EvaluationDeps(
        draft_content="Draft post about hiring a backend engineer.",
        voice_profile={"dominant_tone": "casual", "sample_size": 4},
    )

    prompt = build_diagnostic_prompt("tone", deps)

    assert "subscriber's own writing style" in prompt
    assert "casual" in prompt


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


def test_build_seo_prompt_gemini_only_matches_legacy_prompt():
    deps = EvaluationDeps(
        draft_content="Draft post about hiring a backend engineer.",
        seo_mode="gemini_only",
    )
    assert build_seo_prompt(deps) == build_diagnostic_prompt("seo", deps)


def test_build_seo_prompt_corpus_includes_discoverability_evidence():
    deps = EvaluationDeps(
        draft_content="Hiring backend engineers today.",
        seo_mode="corpus",
        discoverability_context={
            "corpus_benchmark_text": "- Corpus size: 50 posts",
            "deterministic": {
                "deterministic_score": 7.5,
                "signals": [{"check": "hashtag_count", "status": "pass", "note": "ok"}],
            },
            "neighbor_summary": "Neighbor 1: percentile 90",
        },
    )
    prompt = build_seo_prompt(deps)

    assert "Corpus benchmark snapshot" in prompt
    assert "Deterministic draft checks" in prompt
    assert "Nearest historical posts" in prompt
    assert "Hiring backend engineers today." in prompt


def test_build_seo_prompt_corpus_includes_trends_section():
    deps = EvaluationDeps(
        draft_content="Hiring backend engineers today.",
        seo_mode="corpus",
        discoverability_context={
            "trends_text": (
                "External trend signal (Google Trends — web-wide, NOT LinkedIn-specific):\n"
                "- Disclaimer: web-wide only"
            ),
        },
    )
    prompt = build_seo_prompt(deps)

    assert "NOT LinkedIn-specific" in prompt
