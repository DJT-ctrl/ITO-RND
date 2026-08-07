"""Tests for vectorized corpus discovery."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from validation_pipeline.collect_inventory import (
    DatasetInventoryRow,
    build_dataset_inventory_and_unique,
    dataset_inventory_rows,
    estimate_corpus_unique_count,
    unique_post_ids_from_vectorized_datasets,
)
from validation_pipeline.vectorized_corpus import (
    VectorizedDataset,
    _eligible_records,
    _is_linkedin_processed_jsonl,
    discover_vectorized_datasets,
)


def test_is_linkedin_processed_jsonl_filters_flagged_and_meta():
    assert _is_linkedin_processed_jsonl(Path("linkedin_analysed_2026.jsonl"))
    assert not _is_linkedin_processed_jsonl(Path("linkedin_analysed_flagged_x.jsonl"))
    assert not _is_linkedin_processed_jsonl(Path("linkedin_x.jsonl.meta.json"))


def test_eligible_records_requires_content_and_word_count():
    records = [
        {"content": "hello world " * 3, "word_count": 12},
        {"content": "", "word_count": 20},
        {"content": "short", "word_count": 3},
    ]
    assert len(_eligible_records(records)) == 1


@patch("validation_pipeline.vectorized_corpus.list_bundles", return_value=[])
@patch("validation_pipeline.vectorized_corpus.resolve_data_path")
@patch("validation_pipeline.vectorized_corpus.np.load")
@patch("validation_pipeline.vectorized_corpus._match_jsonl_to_npy")
def test_discover_vectorized_datasets_uses_npy_row_matching(
    mock_match,
    mock_np_load,
    mock_resolve,
    _mock_bundles,
):
    processed = Path("/tmp/processed")
    embeddings = Path("/tmp/embeddings")
    jsonl_a = processed / "linkedin_a.jsonl"
    jsonl_b = processed / "linkedin_b.jsonl"
    npy_a = embeddings / "linkedin_gemini_a.npy"

    def resolve_side_effect(path: str) -> Path:
        if path == "data/processed":
            return processed
        if path == "data/embeddings":
            return embeddings
        return Path(path)

    mock_resolve.side_effect = resolve_side_effect
    processed.mkdir(exist_ok=True)
    embeddings.mkdir(exist_ok=True)
    jsonl_a.write_text("{}\n", encoding="utf-8")
    jsonl_b.write_text("{}\n", encoding="utf-8")
    npy_a.write_bytes(b"")
    mock_np_load.return_value = np.zeros((2, 3072))
    mock_match.side_effect = [
        None,
        VectorizedDataset(
            jsonl_path=jsonl_b,
            csv_path=None,
            embeddings_path=npy_a,
            vector_count=2,
        ),
    ]

    datasets = discover_vectorized_datasets(MagicMock())
    assert len(datasets) == 1
    assert datasets[0].jsonl_path.name == "linkedin_b.jsonl"

    jsonl_a.unlink(missing_ok=True)
    jsonl_b.unlink(missing_ok=True)
    npy_a.unlink(missing_ok=True)


def test_unique_post_ids_from_vectorized_datasets_unions_meta(tmp_path: Path):
    npy_a = tmp_path / "a.npy"
    npy_b = tmp_path / "b.npy"
    npy_a.write_bytes(b"")
    npy_b.write_bytes(b"")
    (tmp_path / "a.npy.meta.json").write_text(
        '{"embedding_post_ids": ["1", "2", "2"]}',
        encoding="utf-8",
    )
    (tmp_path / "b.npy.meta.json").write_text(
        '{"embedding_post_ids": ["2", "3"]}',
        encoding="utf-8",
    )
    datasets = [
        VectorizedDataset(
            jsonl_path=tmp_path / "a.jsonl",
            csv_path=None,
            embeddings_path=npy_a,
            vector_count=3,
        ),
        VectorizedDataset(
            jsonl_path=tmp_path / "b.jsonl",
            csv_path=None,
            embeddings_path=npy_b,
            vector_count=2,
        ),
    ]
    assert unique_post_ids_from_vectorized_datasets(datasets) == {"1", "2", "3"}
    assert estimate_corpus_unique_count(datasets) == 3
    rows = dataset_inventory_rows(datasets)
    assert rows[0].unique_ids_available == 2
    assert rows[0].has_meta_ids is True
    rows2, unique = build_dataset_inventory_and_unique(datasets)
    assert unique == 3
    assert rows2[0].unique_ids_available == 2


def test_estimate_corpus_unique_falls_back_to_vector_count(tmp_path: Path):
    npy = tmp_path / "orphan.npy"
    npy.write_bytes(b"")
    datasets = [
        VectorizedDataset(
            jsonl_path=tmp_path / "x.jsonl",
            csv_path=None,
            embeddings_path=npy,
            vector_count=7,
        )
    ]
    assert unique_post_ids_from_vectorized_datasets(datasets) == set()
    assert estimate_corpus_unique_count(datasets) == 7
    row = dataset_inventory_rows(datasets)[0]
    assert row.has_meta_ids is False
    assert row.unique_ids_available == 7
