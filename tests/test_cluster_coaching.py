"""Unit tests for the opt-in cluster-aware coaching stage."""

import asyncio
from types import SimpleNamespace

import agents.cluster_coaching as coaching
from agents.cluster_coaching import (
    CoachingDraft,
    CoachingEvidenceBundle,
    build_cluster_coaching_engine,
    build_cluster_coaching_prompt,
    validate_coaching_output,
)
from agents.schemas import EvaluationDeps, PostEvaluationState
from api.schemas import CoachingEvidence, DetailedCoachingAction
from config.settings import Settings


def _bundle() -> CoachingEvidenceBundle:
    return CoachingEvidenceBundle(
        evidence=CoachingEvidence(
            cluster_id="short_prose_micro",
            cluster_label="short prose posts (micro followers)",
            sample_count=12,
            validated_feedback_count=2,
            confidence="cluster_validated",
            summary="Validated short prose posts in this cluster reward concrete openings.",
        ),
        feedback_lines=["feedback:prediction-1; lesson=Lead with a concrete outcome."],
        neighbor_lines=["neighbor:post-1; percentile=82.0; content=Example"],
        diagnostic_lines=["clarity: score 5; improvements: make the opening specific"],
        allowed_refs=frozenset({"feedback:prediction-1", "neighbor:post-1"}),
    )


def _draft() -> CoachingDraft:
    return CoachingDraft(
        summary="Replace the generic announcement with a reader-facing outcome.",
        primary_action=DetailedCoachingAction(
            title="Make the opening outcome-led",
            draft_anchor="We are excited to announce",
            diagnosis=(
                "The opening expresses enthusiasm but does not tell the reader what changed "
                "or why the announcement matters before they decide whether to continue."
            ),
            edit_instruction=(
                "Replace the generic announcement with the operational outcome, then name the "
                "team member and their role in the following sentence."
            ),
            example_replacement=(
                "Our customers can now complete onboarding in half the time. "
                "That is why we hired a backend engineer to scale the workflow."
            ),
            expected_effect=(
                "A concrete outcome gives the reader a reason to continue before the hiring "
                "announcement shifts attention to the company."
            ),
            evidence_refs=["feedback:prediction-1", "neighbor:post-1"],
        ),
    )


def _settings() -> Settings:
    return Settings(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="test-key",
        raw_data_dir="data/raw",
        default_search_limit=20,
        database_url="postgresql://test/test",
    )


class _CoachAgent:
    async def run(self, prompt, deps):
        return SimpleNamespace(
            output=_draft(),
            usage=lambda: SimpleNamespace(input_tokens=10, output_tokens=5, requests=1),
        )


def test_validate_coaching_output_accepts_real_anchor_and_evidence():
    result = validate_coaching_output(
        _draft(),
        draft_content="We are excited to announce a new backend engineering hire.",
        bundle=_bundle(),
    )

    assert result.status == "ready"
    assert result.primary_action is not None
    assert result.primary_action.priority == "high"


def test_validate_coaching_output_rejects_unknown_evidence_reference():
    draft = _draft()
    draft.primary_action.evidence_refs = ["neighbor:not-provided"]

    try:
        validate_coaching_output(
            draft,
            draft_content="We are excited to announce a new backend engineering hire.",
            bundle=_bundle(),
        )
    except ValueError as exc:
        assert "unavailable evidence" in str(exc)
    else:
        raise AssertionError("unknown evidence must not be exposed")


def test_validate_coaching_output_rejects_anchor_missing_from_draft():
    draft = _draft()
    draft.primary_action.draft_anchor = "This phrase does not exist"

    try:
        validate_coaching_output(
            draft,
            draft_content="We are excited to announce a new backend engineering hire.",
            bundle=_bundle(),
        )
    except ValueError as exc:
        assert "does not appear" in str(exc)
    else:
        raise AssertionError("an unanchored edit must not be exposed")


def test_coaching_prompt_describes_lower_confidence_fallback():
    bundle = _bundle()
    fallback_evidence = bundle.evidence.model_copy(
        update={
            "confidence": "diagnostic_neighbor",
            "validated_feedback_count": 0,
            "summary": "No approved cluster lessons were available.",
        }
    )
    fallback = CoachingEvidenceBundle(
        evidence=fallback_evidence,
        feedback_lines=[],
        neighbor_lines=bundle.neighbor_lines,
        diagnostic_lines=bundle.diagnostic_lines,
        allowed_refs=frozenset({"neighbor:post-1"}),
    )

    prompt = build_cluster_coaching_prompt(
        EvaluationDeps(draft_content="We are excited to announce a new backend engineering hire."),
        fallback,
    )

    assert "lower-confidence" in prompt
    assert "cluster-validated pattern" in prompt
    assert "neighbor:post-1" in prompt


def test_empty_evidence_is_not_a_valid_coaching_result():
    state = PostEvaluationState(draft_content="Draft text")
    assert state.cluster_coaching is None
    assert asyncio.run(_state_is_uncoached(state)) is True


async def _state_is_uncoached(state: PostEvaluationState) -> bool:
    return state.cluster_coaching is None


def test_coaching_engine_writes_only_the_coaching_result(monkeypatch):
    monkeypatch.setattr(coaching, "load_coaching_evidence", lambda *args, **kwargs: _bundle())
    monkeypatch.setattr(coaching, "build_cluster_coaching_agent", lambda model=None: _CoachAgent())
    state = PostEvaluationState(
        draft_content="We are excited to announce a new backend engineering hire.",
        predictor_result={"predicted_engagement_percentile": 72.0},
        diagnostics={"clarity": {"score": 5.0}},
        variants=[{"variant_text": "existing variant"}],
    )

    asyncio.run(build_cluster_coaching_engine(_settings())(state))

    assert state.cluster_coaching is not None
    assert state.predictor_result == {"predicted_engagement_percentile": 72.0}
    assert state.diagnostics == {"clarity": {"score": 5.0}}
    assert state.variants == [{"variant_text": "existing variant"}]
    assert state.errors == []


def test_coaching_engine_failure_is_non_fatal(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("feedback store unavailable")

    monkeypatch.setattr(coaching, "load_coaching_evidence", _raise)
    monkeypatch.setattr(coaching, "build_cluster_coaching_agent", lambda model=None: _CoachAgent())
    state = PostEvaluationState(draft_content="We are excited to announce a new backend engineering hire.")

    asyncio.run(build_cluster_coaching_engine(_settings())(state))

    assert state.cluster_coaching is None
    assert state.errors == ["cluster_coaching: feedback store unavailable"]
