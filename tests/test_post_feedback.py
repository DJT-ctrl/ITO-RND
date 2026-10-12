"""Unit tests for stored-post feedback (no live DB / Gemini required)."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic_ai.models.test import TestModel

from post_feedback.generate import generate_post_feedback
from post_feedback.prompt import (
    build_evidence,
    build_neighbor_notes,
    build_post_feedback_prompt,
    labels_present,
    select_neighbors,
)
from post_feedback.schemas import EligiblePost
from post_feedback.store import _FETCH_ELIGIBLE_SQL, _INSERT_SQL, insert_post_feedback


def _post(**overrides) -> EligiblePost:
    base = dict(
        post_id="p1",
        content="A question about shipping faster.",
        engagement_percentile=70.0,
        engagement_zscore=0.4,
        word_count=120,
        hashtag_count=2,
        has_media=False,
        hook_type="question",
        tone="professional",
        topic="shipping",
        has_explicit_cta=True,
        writing_style="Short question then a story.",
        gemini_labels={"hook_type": "question", "tone": "professional", "topic": "shipping"},
        huggingface_labels={
            "labeler": "huggingface",
            "hook_strength": {"score": 0.8, "category": "Strong Hook"},
            "clarity": {"score": 0.7, "category": "Clear"},
        },
    )
    base.update(overrides)
    return EligiblePost(**base)


def _neighbors() -> list[dict]:
    return [
        {
            "post_id": "p1",
            "engagement_percentile": 70.0,
            "hook_type": "question",
            "topic": "shipping",
            "word_count": 120,
        },
        {
            "post_id": "n1",
            "engagement_percentile": 88.0,
            "hook_type": "story",
            "topic": "shipping",
            "word_count": 80,
        },
    ]


def test_labels_present_requires_a_real_section():
    empty_gemini = {
        "labeler": "gemini",
        "hook_type": None,
        "tone": None,
        "topic": None,
        "writing_style": None,
        "has_explicit_cta": None,
    }
    assert labels_present(empty_gemini, None) is False
    assert labels_present({}, {}) is False
    assert labels_present({"hook_type": "question"}, None) is True
    assert labels_present(None, {"labeler": "huggingface"}) is True
    assert labels_present({"has_explicit_cta": False}, None) is True


def test_fetch_sql_excludes_anomalies_unlabelled_and_existing_rows():
    assert "engagement_anomaly_flag = FALSE" in _FETCH_ELIGIBLE_SQL
    assert "post_feedback" in _FETCH_ELIGIBLE_SQL
    assert "huggingface_labels->>'labeler'" in _FETCH_ELIGIBLE_SQL
    assert "gemini_labels->>'hook_type'" in _FETCH_ELIGIBLE_SQL
    assert "ON CONFLICT (post_id) DO NOTHING" in _INSERT_SQL


def test_prompt_includes_supplied_evidence_only():
    notes = build_neighbor_notes(
        _post(),
        _neighbors(),
        cta_by_id={"n1": False},
    )
    prompt = build_post_feedback_prompt(_post(), notes)
    assert "<post_content>" in prompt
    assert "engagement_percentile=70.0" in prompt
    assert "Strong Hook" in prompt
    assert "n1" in prompt
    assert "hook story vs question" in prompt
    assert "not-a-real-label" not in prompt
    assert "invent" in prompt.lower() or "Do not invent" in prompt


def test_neighbor_notes_drop_self_and_record_the_gap():
    notes = build_neighbor_notes(_post(), _neighbors(), cta_by_id={"n1": False})
    assert select_neighbors(_neighbors(), "p1")[0]["post_id"] == "n1"
    assert len(notes) == 1
    assert notes[0]["percentile_versus_this_post"] == 18.0
    assert "length 80 words vs 120" in notes[0]["label_difference"]
    assert "cta False vs True" in notes[0]["label_difference"]


def test_generate_post_feedback_with_test_model():
    notes = build_neighbor_notes(_post(), _neighbors(), cta_by_id={"n1": False})
    model = TestModel(
        custom_output_args={
            "summary": "Question hook landed at the 70th percentile versus neighbor n1.",
            "what_worked": ["Strong Hook category matches the question opening."],
            "what_to_change": ["Move toward the 80 word length of n1."],
        }
    )
    record = generate_post_feedback(_post(), notes, model=model)
    assert record.post_id == "p1"
    assert record.review_status == "pending"
    assert record.model == "test-model"
    assert record.neighbor_notes[0]["post_id"] == "n1"
    assert record.evidence["hook_type"] == "question"
    assert "70" in record.summary


def test_generate_rejects_ungrounded_writeup():
    model = TestModel(
        custom_output_args={
            "summary": "This will definitely go viral with everyone.",
            "what_worked": ["People love this energy."],
            "what_to_change": ["Add more excitement."],
        }
    )
    with pytest.raises(ValueError, match="grounding"):
        generate_post_feedback(_post(), [], model=model)


def test_insert_is_idempotent_per_post():
    notes = build_neighbor_notes(_post(), _neighbors())
    evidence = build_evidence(_post(), notes)
    from post_feedback.schemas import PostFeedbackRecord

    record = PostFeedbackRecord(
        post_id="p1",
        summary="Question hook at the 70th percentile.",
        what_worked=["Strong Hook"],
        what_to_change=["Shorten toward n1."],
        neighbor_notes=notes,
        evidence=evidence,
        review_status="approved",
        model="test-model",
    )

    class _Cursor:
        def __init__(self, row):
            self.row = row
            self.payload = None

        def execute(self, sql, payload):
            assert "ON CONFLICT (post_id) DO NOTHING" in sql
            self.payload = payload

        def fetchone(self):
            return self.row

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _Conn:
        def __init__(self, row):
            self._cursor = _Cursor(row)
            self.committed = False

        def cursor(self, row_factory=None):
            return self._cursor

        def commit(self):
            self.committed = True

    conflict = _Conn(None)
    assert insert_post_feedback(conflict, record) is None
    assert conflict.committed is True
    assert conflict._cursor.payload["review_status"] == "pending"

    inserted = _Conn((UUID("11111111-1111-1111-1111-111111111111"),))
    assert insert_post_feedback(inserted, record) == UUID(
        "11111111-1111-1111-1111-111111111111"
    )
