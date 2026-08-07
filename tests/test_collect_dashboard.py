"""Tests for Collect dashboard snapshot and Lane A coverage stats."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from validation_pipeline.collect_dashboard import (
    LaneACoverageStats,
    build_collect_dashboard_snapshot,
    fetch_lane_a_coverage_stats,
)
from validation_pipeline.collect_inventory import DatasetInventoryRow
from validation_pipeline.vectorized_corpus import VectorizedDataset


def test_build_collect_dashboard_snapshot_remaining_math():
    settings = MagicMock()
    settings.database_url = "postgresql://x"
    settings.validation_fixed_horizon_enabled = False
    settings.validation_multi_horizon_enabled = True
    settings.validation_multi_horizon_max_predicts_per_run = 40

    datasets = [
        VectorizedDataset(
            jsonl_path=Path("a.jsonl"),
            csv_path=None,
            embeddings_path=Path("a.npy"),
            vector_count=100,
        )
    ]
    inventory = [
        DatasetInventoryRow(
            label="a",
            jsonl_name="a.jsonl",
            embeddings_name="a.npy",
            vector_count=100,
            unique_ids_available=100,
            has_meta_ids=True,
        )
    ]
    lane_a = LaneACoverageStats(
        same_age_total=30,
        same_age_validated=28,
        same_age_failed=2,
        lane_b_scheduled=12,
        age_bucket_counts={"0_6": 10, "6_12": 20},
        recent_same_age_created=5,
    )

    with (
        patch(
            "validation_pipeline.vectorized_corpus.discover_vectorized_datasets",
            return_value=datasets,
        ),
        patch(
            "validation_pipeline.collect_dashboard.build_dataset_inventory_and_unique",
            return_value=(inventory, 100),
        ),
        patch(
            "validation_pipeline.collect_dashboard.pydantic_ai_gemini_model",
            return_value="gemini-test",
        ),
        patch("storage.vector_store.get_connection") as mock_get_conn,
        patch(
            "validation_pipeline.collect_dashboard.fetch_lane_a_coverage_stats",
            return_value=lane_a,
        ),
    ):
        mock_get_conn.return_value = MagicMock()
        snap = build_collect_dashboard_snapshot(settings)

    assert snap.corpus_unique == 100
    assert snap.predicted_lane_a == 30
    assert snap.remaining_lane_a == 70
    assert snap.lane_b_scheduled == 12  # tracked but not in remaining
    assert snap.lane_a_only is True
    assert snap.age_bucket_counts == {"0_6": 10, "6_12": 20}
    assert snap.predicted_last_24h == 5
    assert snap.model_name == "gemini-test"


def test_build_snapshot_lane_b_active_when_fixed_horizons_on():
    settings = MagicMock()
    settings.database_url = ""
    settings.validation_fixed_horizon_enabled = True
    settings.validation_multi_horizon_max_predicts_per_run = 40

    with (
        patch(
            "validation_pipeline.vectorized_corpus.discover_vectorized_datasets",
            return_value=[],
        ),
        patch(
            "validation_pipeline.collect_dashboard.build_dataset_inventory_and_unique",
            return_value=([], 0),
        ),
        patch(
            "validation_pipeline.collect_dashboard.pydantic_ai_gemini_model",
            return_value="m",
        ),
    ):
        snap = build_collect_dashboard_snapshot(settings)

    assert snap.lane_a_only is False
    assert snap.remaining_lane_a == 0
    assert snap.database_available is False


def test_fetch_lane_a_coverage_stats_queries(monkeypatch):
    from validation_pipeline.collect_dashboard import fetch_lane_a_coverage_stats

    calls: list[str] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            calls.append(sql)

        def fetchone(self):
            # same_age_total, validated, failed, scheduled, lane_b, recent
            return (4, 3, 1, 0, 9, 2)

        def fetchall(self):
            return [("0_6", 3.0, 2), ("", 30.0, 1)]

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    stats = fetch_lane_a_coverage_stats(FakeConn())
    assert stats.same_age_total == 4
    assert stats.same_age_validated == 3
    assert stats.same_age_failed == 1
    assert stats.lane_b_scheduled == 9
    assert stats.recent_same_age_created == 2
    assert stats.age_bucket_counts["0_6"] == 2
    assert "24_36" in stats.age_bucket_counts  # derived from horizon 30
    assert any("same_age" in sql for sql in calls)
