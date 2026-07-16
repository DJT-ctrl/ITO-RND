"""Tests for bulk corpus import helpers."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from validation_pipeline.corpus_import import (
    CorpusImportResult,
    dedupe_collected_posts,
)
from validation_pipeline.reset import reset_validation_data
from validation_pipeline.schemas import CollectedPost


def _post(post_id: str) -> CollectedPost:
    return CollectedPost(
        linkedin_post_id=post_id,
        linkedin_url=f"https://www.linkedin.com/posts/{post_id}",
        content="hello",
        posted_at=datetime(2026, 7, 4, tzinfo=timezone.utc),
        likes=1,
        comments=0,
        shares=0,
        total_engagement=1,
    )


def test_dedupe_collected_posts_keeps_first_occurrence():
    posts = [_post("a"), _post("b"), _post("a"), _post("c")]
    assert [p.linkedin_post_id for p in dedupe_collected_posts(posts)] == ["a", "b", "c"]


def test_reset_validation_data_deletes_child_tables_first():
    conn = MagicMock()
    cursor = MagicMock()
    cursor.rowcount = 3
    conn.cursor.return_value.__enter__.return_value = cursor

    with patch("validation_pipeline.reset.create_schema"):
        result = reset_validation_data(conn)

    assert result.predictions == 3
    assert result.prediction_feedback == 3
    conn.commit.assert_called_once()
    executed = [call.args[0] for call in cursor.execute.call_args_list]
    assert executed[0].startswith("DELETE FROM prediction_feedback")
    assert executed[-1].startswith("DELETE FROM prediction_clusters")


def test_corpus_import_result_tracks_loaded_count():
    result = CorpusImportResult(loaded=5, imported=2, skipped=3)
    assert result.loaded == 5
    assert result.imported == 2
