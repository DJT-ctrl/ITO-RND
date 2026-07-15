"""Tests for Phase D feedback retrieval and prompt injection."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from agents.predictor import build_predictor_prompt
from agents.schemas import EvaluationDeps
from feedback.retrieve import (
    fetch_cluster_feedback,
    format_feedback_context_block,
)
from feedback.schemas import DeltaSummary, FeedbackPayload, FeedbackRecord
from validation_pipeline.predict import _load_feedback_context


def _record(*, cluster_id: str = "short_prose_micro", direction: str = "overestimated") -> FeedbackRecord:
    prediction_id = uuid4()
    delta = -12.0 if direction == "overestimated" else 8.0
    payload = FeedbackPayload(
        prediction_id=prediction_id,
        delta_summary=DeltaSummary(
            predicted_percentile=70.0,
            actual_percentile=70.0 + delta,
            prediction_delta=delta,
            direction=direction,  # type: ignore[arg-type]
        ),
        what_worked=["Neighbor set was relevant."],
        what_missed=["Overestimated viral tail."],
        lessons_for_similar_posts=["Bias ~12 pts lower vs neighbor average."],
        cluster_id=cluster_id,
    )
    return FeedbackRecord(
        feedback_id=uuid4(),
        prediction_id=prediction_id,
        cluster_id=cluster_id,
        feedback_json=payload,
        feedback_version="v1",
        generated_at=datetime.now(timezone.utc),
        generation_method="template",
    )


def test_format_feedback_context_block_empty():
    assert format_feedback_context_block([]) == ""


def test_format_feedback_context_block_includes_lessons():
    block = format_feedback_context_block(
        [_record()],
        cluster_id="short_prose_micro",
    )
    assert "cluster `short_prose_micro`" in block
    assert "overestimated" in block
    assert "Lesson:" in block
    assert "Do not change the deterministic percentile" in block


def test_build_predictor_prompt_includes_feedback_section():
    block = format_feedback_context_block([_record()])
    prompt = build_predictor_prompt(
        EvaluationDeps(
            draft_content="Draft about shipping faster.",
            feedback_context=block,
        )
    )
    assert "Validated prediction feedback" in prompt
    assert "Bias ~12 pts lower" in prompt


def test_build_predictor_prompt_omits_feedback_when_absent():
    prompt = build_predictor_prompt(
        EvaluationDeps(draft_content="Draft about shipping faster.")
    )
    assert "Validated prediction feedback" not in prompt


def test_fetch_cluster_feedback_excludes_prediction():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    excluded = uuid4()
    keep_id = uuid4()
    payload = FeedbackPayload(
        prediction_id=keep_id,
        delta_summary=DeltaSummary(
            predicted_percentile=50.0,
            actual_percentile=55.0,
            prediction_delta=5.0,
            direction="accurate",
        ),
        lessons_for_similar_posts=["ok"],
        cluster_id="short_prose_micro",
    )
    cursor.fetchall.return_value = [
        (
            uuid4(),
            keep_id,
            "short_prose_micro",
            payload.model_dump(mode="json"),
            "v1",
            datetime.now(timezone.utc),
            "template",
        )
    ]

    rows = fetch_cluster_feedback(
        conn,
        "short_prose_micro",
        limit=5,
        exclude_prediction_id=excluded,
    )
    assert len(rows) == 1
    sql = cursor.execute.call_args[0][0]
    assert "prediction_id <>" in sql
    assert excluded in cursor.execute.call_args[0][1]


def test_load_feedback_context_disabled():
    settings = MagicMock()
    settings.validation_feedback_injection_enabled = False
    block, cluster_id, count = _load_feedback_context(
        settings, content="hello world"
    )
    assert block is None
    assert cluster_id is None
    assert count == 0


@patch("validation_pipeline.predict.get_connection")
@patch("validation_pipeline.predict.create_schema")
@patch("validation_pipeline.predict.fetch_cluster_centroids")
@patch("validation_pipeline.predict.fetch_cluster_rollup")
@patch("validation_pipeline.predict.fetch_cluster_feedback")
def test_load_feedback_context_formats_records(
    mock_fetch,
    mock_rollup,
    mock_centroids,
    _mock_schema,
    mock_conn,
):
    settings = MagicMock()
    settings.validation_feedback_injection_enabled = True
    settings.validation_feedback_injection_limit = 5
    settings.validation_feedback_injection_format = "lessons"
    mock_conn.return_value = MagicMock()
    mock_centroids.return_value = []
    mock_rollup.return_value = (None, None, 0)
    mock_fetch.return_value = [_record()]

    block, cluster_id, count = _load_feedback_context(
        settings,
        content="A calm product update with enough words here.",
        follower_count=2000,
    )
    assert count == 1
    assert cluster_id == "short_prose_micro"
    assert block is not None
    assert "Lesson:" in block
    assert "feedback_lesson" in block


def test_format_rollup_top2_includes_bias_and_two_examples():
    records = [
        _record(direction="overestimated"),
        _record(direction="underestimated"),
        _record(direction="accurate"),
    ]
    block = format_feedback_context_block(
        records,
        cluster_id="short_prose_micro",
        injection_format="rollup_top2",
        rollup_summary="Cluster roll-up text here.",
        mean_delta=-4.5,
        sample_count=12,
    )
    assert "Cluster roll-up:" in block
    assert "Structured bias:" in block
    assert "cluster_mean_delta" in block
    assert "1." in block
    assert "2." in block
    assert "3." not in block


def test_format_contrastive_pair_labels_miss_and_near():
    big = _record(direction="overestimated")
    near = _record(direction="accurate")
    block = format_feedback_context_block(
        [big, near],
        cluster_id="short_prose_micro",
        injection_format="rollup_contrastive",
        rollup_summary="Summary",
        mean_delta=2.0,
        sample_count=5,
    )
    assert "Contrastive pair:" in block
    assert "Big miss:" in block
    assert "Near hit:" in block
    assert "Structured bias:" in block


def test_select_contrastive_pair_picks_extremes():
    from feedback.retrieve import select_contrastive_pair

    miss = _record(direction="overestimated")
    near = _record(direction="accurate")
    mid = _record(direction="underestimated")
    # Force deltas via payload
    miss.feedback_json.delta_summary.prediction_delta = -30.0
    near.feedback_json.delta_summary.prediction_delta = 1.0
    mid.feedback_json.delta_summary.prediction_delta = 10.0
    got_miss, got_near = select_contrastive_pair([mid, miss, near])
    assert got_miss is miss
    assert got_near is near


def test_example_limit_for_format():
    from feedback.retrieve import example_limit_for_format

    assert example_limit_for_format("lessons", 5) == 5
    assert example_limit_for_format("rollup_top2", 5) == 2
    assert example_limit_for_format("rollup_contrastive", 5) == 8
