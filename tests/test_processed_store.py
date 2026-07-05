"""Unit tests for ProcessedStore's CSV + JSONL persistence (storage/processed_store.py)."""

import json

import pytest

from storage.processed_store import ProcessedStore

SAMPLE_RECORDS = [
    {"post_id": "1", "total_engagement": 10},
    {"post_id": "2", "total_engagement": 20},
]


def test_save_writes_csv_with_header_and_rows(tmp_path):
    store = ProcessedStore(base_dir=str(tmp_path))
    path = store.save("linkedin", SAMPLE_RECORDS)

    assert path.exists()
    assert path.suffix == ".csv"
    lines = path.read_text().splitlines()
    assert lines[0] == "post_id,total_engagement"
    assert len(lines) == 3  # header + 2 rows


def test_save_raises_on_empty_records(tmp_path):
    store = ProcessedStore(base_dir=str(tmp_path))
    with pytest.raises(ValueError):
        store.save("linkedin", [])


def test_save_jsonl_writes_one_json_object_per_line(tmp_path):
    store = ProcessedStore(base_dir=str(tmp_path))
    path = store.save_jsonl("linkedin", SAMPLE_RECORDS)

    assert path.exists()
    assert path.suffix == ".jsonl"
    lines = path.read_text().splitlines()
    assert len(lines) == len(SAMPLE_RECORDS)
    parsed = [json.loads(line) for line in lines]
    assert parsed == SAMPLE_RECORDS


def test_save_jsonl_raises_on_empty_records(tmp_path):
    store = ProcessedStore(base_dir=str(tmp_path))
    with pytest.raises(ValueError):
        store.save_jsonl("linkedin", [])


def test_save_and_save_jsonl_both_create_base_dir(tmp_path):
    nested_dir = tmp_path / "nested" / "processed"
    store = ProcessedStore(base_dir=str(nested_dir))
    store.save("linkedin", SAMPLE_RECORDS)
    assert nested_dir.exists()
