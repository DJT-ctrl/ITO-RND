"""Tests for bulk corpus import helpers."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from validation_pipeline.corpus_import import (
    CorpusImportResult,
    dedupe_collected_posts,
    partition_posts_by_existing_predictions,
    select_posts_for_predict,
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
    assert result.feedback_jobs == 3
    conn.commit.assert_called_once()
    executed = [call.args[0] for call in cursor.execute.call_args_list]
    assert executed[0] == "DELETE FROM feedback_jobs"
    assert "DELETE FROM prediction_feedback" in executed
    assert "DELETE FROM predictions" in executed
    assert executed[-1].startswith("DELETE FROM prediction_clusters")
    assert executed.index("DELETE FROM feedback_jobs") < executed.index(
        "DELETE FROM predictions"
    )

def test_corpus_import_result_tracks_loaded_count():
    result = CorpusImportResult(loaded=5, imported=2, skipped=3)
    assert result.loaded == 5
    assert result.imported == 2


def test_partition_posts_by_existing_predictions():
    posts = [_post("a"), _post("b"), _post("c")]
    settings = MagicMock()
    settings.validation_multi_horizon_enabled = False

    with (
        patch("validation_pipeline.corpus_import.get_connection") as mock_conn,
        patch("validation_pipeline.corpus_import.create_schema"),
        patch(
            "validation_pipeline.corpus_import.existing_prediction_post_ids",
            return_value={"a", "c"},
        ),
    ):
        mock_conn.return_value = MagicMock()
        pending, already = partition_posts_by_existing_predictions(posts, settings)

    assert [p.linkedin_post_id for p in pending] == ["b"]
    assert [p.linkedin_post_id for p in already] == ["a", "c"]
    mock_conn.return_value.close.assert_called_once()


def test_partition_multi_horizon_same_age_stable_across_hour_drift():
    """Lane A completeness must not depend on the exact stored horizon hour."""
    from validation_pipeline.age_buckets import LANE_SAME_AGE

    posts = [_post("a"), _post("b")]
    settings = MagicMock()
    settings.validation_multi_horizon_enabled = True
    settings.validation_fixed_horizon_enabled = False

    with (
        patch("validation_pipeline.corpus_import.get_connection") as mock_conn,
        patch("validation_pipeline.corpus_import.create_schema"),
        patch(
            "validation_pipeline.multi_horizon.planned_horizons_for_post",
            side_effect=[
                [(LANE_SAME_AGE, 50)],  # planner wants 50h now
                [(LANE_SAME_AGE, 12)],
            ],
        ),
        patch(
            "validation_pipeline.store.existing_prediction_lanes_and_keys",
            return_value=({("a", 49.0)}, {"a"}),  # stored at 49h; still counts
        ),
    ):
        mock_conn.return_value = MagicMock()
        pending, already = partition_posts_by_existing_predictions(posts, settings)

    assert [p.linkedin_post_id for p in already] == ["a"]
    assert [p.linkedin_post_id for p in pending] == ["b"]


def test_prediction_progress_counts_done_waiting_remaining():
    from validation_pipeline.corpus_import import prediction_progress_counts

    posts = [_post("done"), _post("wait"), _post("new")]
    settings = MagicMock()
    settings.database_url = "postgresql://x"

    coverage = {
        "done": {
            "has_any": True,
            "has_same_age": True,
            "has_scheduled": False,
            "has_validated": True,
        },
        "wait": {
            "has_any": True,
            "has_same_age": True,
            "has_scheduled": True,
            "has_validated": True,
        },
    }
    with (
        patch("validation_pipeline.corpus_import.get_connection") as mock_conn,
        patch("validation_pipeline.corpus_import.create_schema"),
        patch(
            "validation_pipeline.store.prediction_post_coverage",
            return_value=coverage,
        ),
    ):
        mock_conn.return_value = MagicMock()
        counts = prediction_progress_counts(posts, settings)

    assert counts.total == 3
    assert counts.done == 1
    assert counts.waiting == 1
    assert counts.remaining == 1


def test_select_posts_for_predict_skips_before_max_posts():
    """Already-predicted head of the corpus must not consume the max_posts budget."""
    posts = [_post("done-1"), _post("done-2"), _post("new-1"), _post("new-2"), _post("new-3")]
    settings = MagicMock()

    with patch(
        "validation_pipeline.corpus_import.partition_posts_by_existing_predictions",
        return_value=(
            [_post("new-1"), _post("new-2"), _post("new-3")],
            [_post("done-1"), _post("done-2")],
        ),
    ):
        selected, skipped = select_posts_for_predict(
            posts,
            settings,
            max_posts=2,
            skip_existing=True,
        )

    assert skipped == 2
    assert [p.linkedin_post_id for p in selected] == ["new-1", "new-2"]


def test_select_posts_for_predict_respects_skip_existing_false():
    posts = [_post("a"), _post("b"), _post("c")]
    settings = MagicMock()

    with patch(
        "validation_pipeline.corpus_import.partition_posts_by_existing_predictions"
    ) as mock_partition:
        selected, skipped = select_posts_for_predict(
            posts,
            settings,
            max_posts=2,
            skip_existing=False,
        )

    mock_partition.assert_not_called()
    assert skipped == 0
    assert [p.linkedin_post_id for p in selected] == ["a", "b"]


def test_bulk_import_vectorized_filters_before_predict():
    """Regression: skip already-done posts while scanning; stop at max_posts."""
    import asyncio
    from pathlib import Path

    from validation_pipeline.vectorized_corpus import (
        VectorizedDataset,
        bulk_import_vectorized_and_predict_async,
    )

    settings = MagicMock()
    settings.database_url = "postgresql://x"
    settings.validation_multi_horizon_enabled = True
    settings.validation_fixed_horizon_enabled = False
    predicted_ids: list[str] = []

    dataset = VectorizedDataset(
        jsonl_path=Path("linkedin_a.jsonl"),
        csv_path=None,
        embeddings_path=Path("a.npy"),
        vector_count=4,
    )

    async def fake_predict(selected, _settings, **_kwargs):
        predicted_ids.extend(p.linkedin_post_id for p in selected)
        return CorpusImportResult(loaded=len(selected), imported=len(selected))

    with (
        patch(
            "validation_pipeline.vectorized_corpus.discover_vectorized_datasets",
            return_value=[dataset],
        ),
        patch(
            "validation_pipeline.vectorized_corpus.load_collected_posts_from_vectorized_datasets",
            return_value=(
                [_post("done-1"), _post("done-2"), _post("new-1"), _post("new-2")],
                [dataset],
            ),
        ),
        patch("storage.vector_store.get_connection") as mock_conn,
        patch("storage.vector_store.create_schema"),
        patch(
            "validation_pipeline.store.fetch_import_skip_post_ids",
            return_value={"done-1", "done-2"},
        ),
        patch(
            "validation_pipeline.corpus_import.predict_on_posts_async",
            side_effect=fake_predict,
        ),
    ):
        mock_conn.return_value = MagicMock()
        result = asyncio.run(
            bulk_import_vectorized_and_predict_async(
                settings,
                max_posts=1,
                skip_existing=True,
            )
        )

    assert predicted_ids == ["new-1"]
    assert result.imported == 1
    assert result.skipped == 2
