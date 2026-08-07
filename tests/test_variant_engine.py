"""Unit tests for the T3.4 Variant Optimisation Engine."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from pydantic_ai.models.test import TestModel

from agents.cross_reference import (
    CrossReferenceAnalysisItem,
    CrossReferenceAnalysisOutput,
    apply_cross_reference_analysis,
    select_cross_references,
)
from agents.predictor import build_predictor_agent
from agents.schemas import EvaluationDeps, PostEvaluationState
from agents.variant_engine import (
    VariantDraftSet,
    build_variant_engine,
    build_variant_generation_agent,
    build_variant_prompt,
)
from agents.prompt_safety import PROMPT_DATA_PREAMBLE
from api.schemas import SimilarPost


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


def full_state() -> PostEvaluationState:
    return PostEvaluationState(
        draft_content="Excited to announce our new product launch!",
        similar_posts=[fake_post("1")],
        predictor_result={
            "predicted_engagement_percentile": 55.0,
            "predicted_total_engagement": 30,
            "reasoning": "Middling hook, no CTA.",
        },
        diagnostics={
            "seo": {"score": 4.0, "flaws": ["no hashtags"], "advantages": [], "improvements": ["add hashtags"]},
            "clarity": {"score": 8.0, "flaws": [], "advantages": ["clear point"], "improvements": []},
            "tone": {"score": 6.0, "flaws": ["too formal"], "advantages": [], "improvements": ["loosen tone"]},
        },
    )


class _FixedPredictorAgent:
    """Duck-typed predictor stand-in returning an increasing score per call,
    so we can deterministically assert on descending-sort ranking."""

    def __init__(self):
        self._calls = 0

    async def run(self, prompt: str, deps) -> SimpleNamespace:
        self._calls += 1
        # First variant gets lowest score, later variants get higher scores,
        # so sorting must reorder them (proves sort isn't accidentally a no-op).
        percentile = 40.0 + self._calls * 10.0
        return SimpleNamespace(
            output=SimpleNamespace(
                predicted_engagement_percentile=percentile,
                predicted_total_engagement=int(percentile),
            )
        )


class _RaisingPredictorAgent:
    """Fails on the 2nd call only, succeeds otherwise."""

    def __init__(self):
        self._calls = 0

    async def run(self, prompt: str, deps) -> SimpleNamespace:
        self._calls += 1
        if self._calls == 2:
            raise RuntimeError("predictor boom")
        return SimpleNamespace(
            output=SimpleNamespace(predicted_engagement_percentile=70.0, predicted_total_engagement=50)
        )


class _RecordingPredictorAgent:
    def __init__(self):
        self.cross_references = []

    async def run(self, prompt: str, deps) -> SimpleNamespace:
        self.cross_references.append(deps.cross_references)
        return SimpleNamespace(
            output=SimpleNamespace(predicted_engagement_percentile=70.0, predicted_total_engagement=50)
        )


def test_prompt_includes_predictor_diagnostics_and_neighbors():
    state = full_state()
    deps = EvaluationDeps(draft_content=state.draft_content, similar_posts=state.similar_posts)

    prompt = build_variant_prompt("dimension", deps, state)

    assert PROMPT_DATA_PREAMBLE in prompt
    assert "<post_content>" in prompt
    assert "Middling hook, no CTA." in prompt
    assert "no hashtags" in prompt
    assert "loosen tone" in prompt
    assert "Neighbor 1" in prompt
    assert "Strong launch post" in prompt


def test_prompt_flags_missing_diagnostics_for_dimension_strategy():
    state = full_state()
    state.diagnostics.pop("tone")
    deps = EvaluationDeps(draft_content=state.draft_content, similar_posts=state.similar_posts)

    prompt = build_variant_prompt("dimension", deps, state)

    assert "Missing diagnostics: tone" in prompt


def test_prompt_includes_completed_cross_reference_feedback():
    state = full_state()
    stronger = fake_post("stronger")
    stronger.engagement_percentile = 92.0
    state.cross_references = apply_cross_reference_analysis(
        select_cross_references([stronger], {"percentile": 70.0}),
        CrossReferenceAnalysisOutput(
            references=[
                CrossReferenceAnalysisItem(
                    post_id="stronger",
                    observed_strengths=["Outcome-led opening"],
                    suggested_adaptation="Lead with one concrete outcome.",
                )
            ],
            overall_feedback=["Make the opening more specific."],
        ),
    )
    deps = EvaluationDeps(
        draft_content=state.draft_content,
        similar_posts=state.similar_posts,
        cross_references=state.cross_references,
    )

    prompt = build_variant_prompt("dimension", deps, state)

    assert "Outcome-led opening" in prompt
    assert "Lead with one concrete outcome" in prompt
    assert "Make the opening more specific" in prompt


def test_generation_agent_returns_exactly_three_variants_with_test_model():
    agent = build_variant_generation_agent(TestModel())
    state = full_state()
    deps = EvaluationDeps(draft_content=state.draft_content, similar_posts=state.similar_posts)

    result = asyncio.run(agent.run(build_variant_prompt("dimension", deps, state), deps=deps))

    assert isinstance(result.output, VariantDraftSet)
    assert len(result.output.variants) == 3


def test_finalize_hook_produces_three_variants_sorted_descending():
    state = full_state()
    hook = build_variant_engine(_FixedPredictorAgent(), model=TestModel(), strategy="dimension")

    asyncio.run(hook(state))

    assert len(state.variants) == 3
    percentiles = [v["predicted_engagement_percentile"] for v in state.variants]
    assert percentiles == sorted(percentiles, reverse=True)
    assert state.errors == []


def test_finalize_hook_runs_with_partial_diagnostics():
    state = full_state()
    del state.diagnostics["tone"]
    hook = build_variant_engine(_FixedPredictorAgent(), model=TestModel(), strategy="dimension")

    asyncio.run(hook(state))

    assert len(state.variants) == 3
    assert state.errors == []


def test_finalize_hook_skips_when_nothing_available():
    state = PostEvaluationState(draft_content="Draft with no upstream output.")

    class _AssertNotCalledAgent:
        async def run(self, *args, **kwargs):
            raise AssertionError("predictor agent should not be called")

    # model=TestModel() would still build a real generation agent, but since
    # neither predictor_result nor diagnostics exist the hook must return
    # before ever calling it (or the predictor re-run agent below).
    hook = build_variant_engine(_AssertNotCalledAgent(), model=TestModel(), strategy="dimension")

    asyncio.run(hook(state))

    assert state.variants == []
    assert len(state.errors) == 1
    assert "skipped" in state.errors[0]


def test_finalize_hook_falls_back_when_one_predictor_rerun_fails():
    state = full_state()
    hook = build_variant_engine(_RaisingPredictorAgent(), model=TestModel(), strategy="dimension")

    asyncio.run(hook(state))

    assert len(state.variants) == 3
    # The failed re-run should fall back to the original predictor_result's
    # percentile (55.0) rather than crash the whole hook.
    fallback_present = any(v["predicted_engagement_percentile"] == 55.0 for v in state.variants)
    assert fallback_present
    assert len(state.errors) == 1
    assert "predictor re-run failed" in state.errors[0]


def test_real_predictor_agent_can_be_reused_for_rerun_with_test_model():
    """Proves the variant engine can drive an actual T3.2 predictor Agent
    (not just duck-typed stand-ins), using TestModel so no network call
    happens."""
    predictor_agent = build_predictor_agent(TestModel())
    state = full_state()
    hook = build_variant_engine(predictor_agent, model=TestModel(), strategy="narrative")

    asyncio.run(hook(state))

    assert len(state.variants) == 3
    for variant in state.variants:
        assert 0 <= variant["predicted_engagement_percentile"] <= 100
        assert variant["predicted_total_engagement"] >= 0
    assert state.errors == []


def test_reembed_neighbors_requires_settings_at_build_time():
    """Fail fast at build time (before any request runs) rather than at
    call time, if reembed_neighbors=True but no settings were supplied."""
    with pytest.raises(ValueError):
        build_variant_engine(_FixedPredictorAgent(), model=TestModel(), reembed_neighbors=True, settings=None)


def test_default_shared_neighbors_mode_never_calls_embed_query():
    """reembed_neighbors defaults to False: variants must be scored against
    the shared stage-1 neighbors already in state, with zero extra
    Gemini/DB calls."""
    state = full_state()
    hook = build_variant_engine(_FixedPredictorAgent(), model=TestModel(), strategy="dimension")

    with patch("agents.variant_engine.embed_query") as mock_embed_query, patch(
        "agents.variant_engine.find_similar"
    ) as mock_find_similar:
        asyncio.run(hook(state))

    mock_embed_query.assert_not_called()
    mock_find_similar.assert_not_called()
    assert len(state.variants) == 3


def test_reembed_neighbors_fetches_own_neighbors_per_variant():
    """reembed_neighbors=True: each of the 3 variants should re-embed its
    own text and fetch its own nearest neighbors before being scored."""
    state = full_state()
    fake_settings = SimpleNamespace(gemini_api_key="fake", database_url="postgresql://fake/fake")
    hook = build_variant_engine(
        _FixedPredictorAgent(),
        model=TestModel(),
        strategy="dimension",
        reembed_neighbors=True,
        settings=fake_settings,
    )

    with patch("agents.variant_engine.embed_query", return_value=(np.zeros(3072, dtype=np.float32), 10)) as mock_embed_query, patch(
        "agents.variant_engine.find_similar", return_value=[fake_row("own-neighbor")]
    ) as mock_find_similar, patch("agents.variant_engine.get_connection", return_value=MagicMock()), patch(
        "agents.variant_engine.register_vector"
    ):
        asyncio.run(hook(state))

    assert mock_embed_query.call_count == 3
    assert mock_find_similar.call_count == 6
    # Each call should re-embed the VARIANT's own text, not the original draft.
    embedded_texts = [call.args[0] for call in mock_embed_query.call_args_list]
    assert all(text != state.draft_content for text in embedded_texts)
    assert len(state.variants) == 3
    assert state.errors == []


def test_reembed_neighbors_selects_fresh_global_references_per_variant():
    state = full_state()
    state.retrieval_user_id = "subscriber-1"
    predictor = _RecordingPredictorAgent()
    fake_settings = SimpleNamespace(gemini_api_key="fake", database_url="postgresql://fake/fake")
    hook = build_variant_engine(
        predictor,
        model=TestModel(),
        strategy="dimension",
        reembed_neighbors=True,
        settings=fake_settings,
    )
    ordinary = fake_row("variant-neighbor")
    ordinary["engagement_percentile"] = 40.0
    global_candidate = fake_row("fresh-global-reference")
    global_candidate["engagement_percentile"] = 90.0

    def return_scoped_or_global(*args, **kwargs):
        return [ordinary] if kwargs["user_id"] is not None else [global_candidate]

    with patch("agents.variant_engine.embed_query", return_value=(np.zeros(3072, dtype=np.float32), 10)) as mock_embed_query, patch(
        "agents.variant_engine.find_similar", side_effect=return_scoped_or_global
    ) as mock_find_similar, patch("agents.variant_engine.get_connection", return_value=MagicMock()), patch(
        "agents.variant_engine.register_vector"
    ):
        asyncio.run(hook(state))

    assert mock_embed_query.call_count == 3
    assert mock_find_similar.call_count == 6
    scoped_calls = [
        call for call in mock_find_similar.call_args_list if call.kwargs["user_id"] is not None
    ]
    global_calls = [
        call for call in mock_find_similar.call_args_list if call.kwargs["user_id"] is None
    ]
    assert len(scoped_calls) == 3
    assert len(global_calls) == 3
    assert len(predictor.cross_references) == 3
    assert all(reference.status == "ready" for reference in predictor.cross_references)
    assert all(
        reference.references[0].post.post_id == "fresh-global-reference"
        for reference in predictor.cross_references
    )


def test_reembed_neighbor_fetch_failure_falls_back_gracefully():
    """If re-embedding fails for one variant, that variant falls back to the
    original predictor_result score (like a predictor re-run failure) and
    the other variants are unaffected."""
    state = full_state()
    fake_settings = SimpleNamespace(gemini_api_key="fake", database_url="postgresql://fake/fake")
    hook = build_variant_engine(
        _FixedPredictorAgent(),
        model=TestModel(),
        strategy="dimension",
        reembed_neighbors=True,
        settings=fake_settings,
    )

    with patch(
        "agents.variant_engine.embed_query",
        side_effect=[
            RuntimeError("embed boom"),
            (np.zeros(3072, dtype=np.float32), 10),
            (np.zeros(3072, dtype=np.float32), 10),
        ],
    ), patch("agents.variant_engine.find_similar", return_value=[fake_row("own-neighbor")]), patch(
        "agents.variant_engine.get_connection", return_value=MagicMock()
    ), patch(
        "agents.variant_engine.register_vector"
    ):
        asyncio.run(hook(state))

    assert len(state.variants) == 3
    assert len(state.errors) == 1
    assert "predictor re-run failed" in state.errors[0]
    fallback_present = any(v["predicted_engagement_percentile"] == 55.0 for v in state.variants)
    assert fallback_present
