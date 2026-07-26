"""Unit tests for A1 anomaly post-mortems (no live DB / Gemini required)."""

from __future__ import annotations

from post_mortems.prompt import build_evidence, build_post_mortem_prompt
from post_mortems.schemas import AnomalyPostRow, VERDICTS
from pydantic_ai.models.test import TestModel

from post_mortems.generate import generate_post_mortem


def _row(**overrides) -> AnomalyPostRow:
    base = dict(
        post_id="p1",
        content="Hello world post about shipping.",
        likes=10,
        comments=80,
        shares=1,
        total_engagement=91,
        comment_ratio=8.0,
        share_ratio=0.1,
        engagement_percentile=55.0,
        anomaly_reasons=["comment_ratio_outlier"],
        topic="shipping",
        hook_type="story",
    )
    base.update(overrides)
    return AnomalyPostRow(**base)


def test_build_evidence_includes_machine_reasons():
    evidence = build_evidence(_row())
    assert evidence["comment_ratio"] == 8.0
    assert evidence["machine_reasons"] == ["comment_ratio_outlier"]


def test_prompt_lists_verdicts_and_wraps_content():
    prompt = build_post_mortem_prompt(_row())
    for verdict in VERDICTS:
        assert verdict in prompt
    assert "<post_content>" in prompt
    assert "comment_ratio_outlier" in prompt
    assert "modified z-score" in prompt


def test_generate_post_mortem_with_test_model():
    model = TestModel(
        custom_output_args={
            "verdict": "likely_inorganic",
            "summary": "Comments dwarf likes relative to peers; looks pod-like.",
            "lesson_for_models": "Do not treat this as organic discussion success.",
        }
    )
    record = generate_post_mortem(_row(), model=model)
    assert record.post_id == "p1"
    assert record.verdict == "likely_inorganic"
    assert "pod" in record.summary.lower() or "Comments" in record.summary
    assert record.machine_reasons == ["comment_ratio_outlier"]
    assert record.evidence["likes"] == 10
    assert record.model == "test-model"
