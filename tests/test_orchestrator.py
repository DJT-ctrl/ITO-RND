"""Unit tests for agents/orchestrator.py (T3.1: State Orchestrator Setup).

embed_query()/find_similar()/get_connection()/register_vector() are all
patched inside agents.orchestrator's namespace — no real DB or Gemini calls
in unit tests, per repo convention (see tests/test_embedder.py,
tests/test_vector_store.py, tests/test_api.py).

No real pydantic_ai model calls either: the "agents" registered in these
tests are lightweight stand-ins (either pydantic_ai.Agent wired to
TestModel, or plain duck-typed objects exposing an async `run(prompt,
deps)` method) — this proves the orchestrator's concurrency/state plumbing
without needing network access or real Predictor/Diagnostic logic (that's
T3.2/T3.3, not built yet).
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from agents.orchestrator import run_evaluation_cycle
from agents.schemas import EvaluationDeps
from config.settings import Settings


def fake_row(post_id: str = "1") -> dict:
    return {
        "post_id": post_id,
        "content": "hello world",
        "likes": 10,
        "comments": 2,
        "shares": 1,
        "total_engagement": 13,
        "engagement_percentile": 75.0,
        "engagement_zscore": 0.8,
        "cosine_distance": 0.05,
    }


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


class _SleepyAgent:
    """Duck-typed stand-in for a pydantic_ai.Agent: sleeps, then returns a
    result object exposing `.output`, matching what run_evaluation_cycle
    expects from a real Agent.run() call."""

    def __init__(self, output: dict, sleep_s: float = 0.1):
        self._output = output
        self._sleep_s = sleep_s

    async def run(self, prompt: str, deps) -> SimpleNamespace:
        await asyncio.sleep(self._sleep_s)
        return SimpleNamespace(output=self._output)


class _RaisingAgent:
    """Duck-typed stand-in for an Agent whose run() fails."""

    async def run(self, prompt: str, deps) -> SimpleNamespace:
        raise RuntimeError("boom")


def _patch_neighbor_fetch(rows: list[dict]):
    """Patch the 4 collaborators agents.orchestrator._gather_similar_posts
    uses, so tests never touch a real DB or the Gemini API."""
    return (
        patch("agents.orchestrator.embed_query", return_value=np.zeros(3072, dtype=np.float32)),
        patch("agents.orchestrator.find_similar", return_value=rows),
        patch("agents.orchestrator.get_connection", return_value=MagicMock()),
        patch("agents.orchestrator.register_vector"),
    )


def test_concurrent_agents_run_in_parallel_not_sequentially():
    """5 agents each sleeping ~0.1s should finish in well under 5*0.1s if
    they truly run concurrently via asyncio.gather."""
    p1, p2, p3, p4 = _patch_neighbor_fetch([fake_row("1")])
    with p1, p2, p3, p4:
        diagnostics = {f"check_{i}": _SleepyAgent({"ok": i}, sleep_s=0.1) for i in range(5)}

        start = time.monotonic()
        state = asyncio.run(run_evaluation_cycle("draft text", fake_settings(), diagnostics=diagnostics))
        elapsed = time.monotonic() - start

    assert elapsed < 0.3, f"expected concurrent execution, took {elapsed:.2f}s"
    assert len(state.diagnostics) == 5
    for i in range(5):
        assert state.diagnostics[f"check_{i}"] == {"ok": i}
    assert state.errors == []


def test_one_failing_agent_does_not_drop_other_results():
    p1, p2, p3, p4 = _patch_neighbor_fetch([fake_row("1")])
    with p1, p2, p3, p4:
        diagnostics = {
            "good": _SleepyAgent({"status": "fine"}, sleep_s=0.01),
            "bad": _RaisingAgent(),
        }
        state = asyncio.run(run_evaluation_cycle("draft text", fake_settings(), diagnostics=diagnostics))

    assert state.diagnostics == {"good": {"status": "fine"}}
    assert len(state.errors) == 1
    assert "bad" in state.errors[0]
    assert "boom" in state.errors[0]


def test_predictor_result_written_separately_from_diagnostics():
    p1, p2, p3, p4 = _patch_neighbor_fetch([fake_row("1")])
    with p1, p2, p3, p4:
        predictor = _SleepyAgent({"engagement_score": 88}, sleep_s=0.01)
        diagnostics = {"seo": _SleepyAgent({"seo_score": 5}, sleep_s=0.01)}
        state = asyncio.run(
            run_evaluation_cycle("draft text", fake_settings(), predictor=predictor, diagnostics=diagnostics)
        )

    assert state.predictor_result == {"engagement_score": 88}
    assert state.diagnostics == {"seo": {"seo_score": 5}}


def test_no_state_leaks_between_separate_calls():
    p1, p2, p3, p4 = _patch_neighbor_fetch([fake_row("1")])
    with p1, p2, p3, p4:
        state_a = asyncio.run(
            run_evaluation_cycle(
                "draft A", fake_settings(), diagnostics={"a_check": _SleepyAgent({"a": 1}, sleep_s=0.01)}
            )
        )
        state_b = asyncio.run(
            run_evaluation_cycle(
                "draft B", fake_settings(), diagnostics={"b_check": _SleepyAgent({"b": 2}, sleep_s=0.01)}
            )
        )

    assert state_a.draft_content == "draft A"
    assert state_b.draft_content == "draft B"
    assert "b_check" not in state_a.diagnostics
    assert "a_check" not in state_b.diagnostics
    assert state_a.errors == [] and state_b.errors == []


def test_similar_posts_populated_before_agents_run():
    """Agents should see the neighbor-fetch result already populated on
    `deps.similar_posts` — proves stage 1 (sequential setup) completes
    before stage 2 (concurrent evaluate) starts."""
    rows = [fake_row("1"), fake_row("2"), fake_row("3")]
    p1, p2, p3, p4 = _patch_neighbor_fetch(rows)

    captured: dict = {}

    class _CapturingAgent:
        async def run(self, prompt, deps):
            captured["count"] = len(deps.similar_posts)
            return SimpleNamespace(output={"seen": captured["count"]})

    with p1, p2, p3, p4:
        state = asyncio.run(
            run_evaluation_cycle("draft text", fake_settings(), diagnostics={"capture": _CapturingAgent()})
        )

    assert captured["count"] == 3
    assert len(state.similar_posts) == 3
    assert state.diagnostics["capture"] == {"seen": 3}


def test_no_agents_supplied_returns_empty_placeholders():
    """No predictor/diagnostics registered (T3.2/T3.3 don't exist yet) —
    the cycle should still complete end-to-end with empty placeholder
    fields, not raise."""
    p1, p2, p3, p4 = _patch_neighbor_fetch([fake_row("1")])
    with p1, p2, p3, p4:
        state = asyncio.run(run_evaluation_cycle("draft text", fake_settings()))

    assert state.predictor_result is None
    assert state.diagnostics == {}
    assert state.variants == []
    assert state.errors == []
    assert len(state.similar_posts) == 1


def test_real_pydantic_ai_agent_with_test_model():
    """Proves the orchestrator wires up an actual pydantic_ai.Agent (not
    just duck-typed stand-ins) end-to-end, using TestModel so no real
    network/LLM call happens."""
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    stub_agent: Agent[EvaluationDeps, str] = Agent(
        TestModel(custom_output_text="stub diagnostic output"),
        deps_type=EvaluationDeps,
    )

    p1, p2, p3, p4 = _patch_neighbor_fetch([fake_row("1")])
    with p1, p2, p3, p4:
        state = asyncio.run(
            run_evaluation_cycle("draft text", fake_settings(), diagnostics={"real_agent": stub_agent})
        )

    assert state.diagnostics == {"real_agent": {"result": "stub diagnostic output"}}
    assert state.errors == []


# ── Personalization: user_id / voice_profile ──────────────────────────────


def test_user_id_scopes_neighbor_fetch_and_populates_voice_profile():
    """When user_id is given, find_similar() should be called with it, and
    a fetched voice profile should end up on state + be visible to agents
    via deps.voice_profile."""
    rows = [fake_row("1")]
    profile = {"dominant_tone": "casual", "sample_size": 5}

    captured: dict = {}

    class _CapturingAgent:
        async def run(self, prompt, deps):
            captured["voice_profile"] = deps.voice_profile
            return SimpleNamespace(output={"ok": True})

    p1, p2, p3, p4 = _patch_neighbor_fetch(rows)
    with p1, p2, p3, p4, patch(
        "agents.orchestrator.get_user_voice_profile", return_value=profile
    ) as mock_voice:
        state = asyncio.run(
            run_evaluation_cycle(
                "draft text",
                fake_settings(),
                diagnostics={"capture": _CapturingAgent()},
                user_id="user-1",
            )
        )

    mock_voice.assert_called_once()
    assert mock_voice.call_args[0][1] == "user-1"
    assert state.voice_profile == profile
    assert captured["voice_profile"] == profile


def test_no_user_id_never_calls_voice_profile():
    """Without a user_id, get_user_voice_profile must not be touched at
    all — non-personalized calls behave exactly as before this feature."""
    p1, p2, p3, p4 = _patch_neighbor_fetch([fake_row("1")])
    with p1, p2, p3, p4, patch("agents.orchestrator.get_user_voice_profile") as mock_voice:
        state = asyncio.run(run_evaluation_cycle("draft text", fake_settings()))

    mock_voice.assert_not_called()
    assert state.voice_profile is None


def test_use_voice_profile_false_skips_profile_even_with_user_id():
    p1, p2, p3, p4 = _patch_neighbor_fetch([fake_row("1")])
    with p1, p2, p3, p4, patch("agents.orchestrator.get_user_voice_profile") as mock_voice:
        state = asyncio.run(
            run_evaluation_cycle(
                "draft text", fake_settings(), user_id="user-1", use_voice_profile=False
            )
        )

    mock_voice.assert_not_called()
    assert state.voice_profile is None
