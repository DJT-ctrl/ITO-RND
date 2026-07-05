"""Unit tests for processors/run_embeddings.py (T1.3 batch entry point).

embed_batch/save_embeddings are mocked here — they already have their own
tests in tests/test_embedder.py. This file only exercises the loading,
content re-joining, and file-selection logic that's specific to this script.
"""

import json
from unittest.mock import patch

import numpy as np
import pytest

from config.settings import Settings
from processors.run_embeddings import _join_content, _latest_jsonl, load_and_join, run_embeddings


def make_settings(raw_data_dir: str) -> Settings:
    return Settings(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="test-gemini-key",
        raw_data_dir=raw_data_dir,
        default_search_limit=10,
    )


def make_raw_post(post_id: str, content: str) -> dict:
    return {"id": post_id, "content": content}


# ── _latest_jsonl ────────────────────────────────────────────────────────────

def test_latest_jsonl_picks_most_recent_file(tmp_path):
    (tmp_path / "linkedin_20260101T000000Z.jsonl").write_text("")
    (tmp_path / "linkedin_20260102T000000Z.jsonl").write_text("")

    latest = _latest_jsonl(str(tmp_path))
    assert latest.name == "linkedin_20260102T000000Z.jsonl"


def test_latest_jsonl_raises_when_none_found(tmp_path):
    with pytest.raises(ValueError):
        _latest_jsonl(str(tmp_path))


# ── _join_content ────────────────────────────────────────────────────────────

def test_join_content_attaches_raw_text_by_post_id(tmp_path):
    (tmp_path / "linkedin_20260101T000000Z.json").write_text(
        json.dumps([make_raw_post("1", "Hello world"), make_raw_post("2", "Second post")])
    )
    records = [{"post_id": "1", "word_count": 2}, {"post_id": "2", "word_count": 2}]

    joined = _join_content(records, str(tmp_path))

    assert joined[0]["content"] == "Hello world"
    assert joined[1]["content"] == "Second post"


def test_join_content_defaults_to_empty_string_when_no_match(tmp_path):
    (tmp_path / "linkedin_20260101T000000Z.json").write_text(json.dumps([make_raw_post("1", "Hello")]))
    records = [{"post_id": "missing", "word_count": 5}]

    joined = _join_content(records, str(tmp_path))

    assert joined[0]["content"] == ""


# ── load_and_join ────────────────────────────────────────────────────────────

def test_load_and_join_returns_records_and_path_used(tmp_path):
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    raw_dir.mkdir()
    processed_dir.mkdir()
    (raw_dir / "linkedin_20260101T000000Z.json").write_text(json.dumps([make_raw_post("1", "Hello world")]))
    jsonl_path = processed_dir / "linkedin_20260101T000000Z.jsonl"
    jsonl_path.write_text(json.dumps({"post_id": "1", "word_count": 2}) + "\n")

    settings = make_settings(str(raw_dir))
    joined_records, used_path = load_and_join(str(jsonl_path), settings)

    assert joined_records[0]["content"] == "Hello world"
    assert used_path == jsonl_path


# ── run_embeddings ───────────────────────────────────────────────────────────

def test_run_embeddings_end_to_end(tmp_path):
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    embeddings_dir = tmp_path / "embeddings"
    raw_dir.mkdir()
    processed_dir.mkdir()

    (raw_dir / "linkedin_20260101T000000Z.json").write_text(
        json.dumps([make_raw_post("1", "Hello world this is a long enough post body")])
    )
    jsonl_path = processed_dir / "linkedin_20260101T000000Z.jsonl"
    jsonl_path.write_text(json.dumps({"post_id": "1", "word_count": 9}) + "\n")

    settings = make_settings(str(raw_dir))
    fake_vectors = np.zeros((1, 3072), dtype=np.float32)

    with patch("processors.run_embeddings.embed_batch", return_value=(fake_vectors, 0)) as mock_embed, patch(
        "processors.run_embeddings.save_embeddings"
    ) as mock_save:
        mock_save.return_value = embeddings_dir / "linkedin_gemini_20260101T000000Z.npy"
        out_path = run_embeddings(processed_file=str(jsonl_path), settings=settings)

    # Content was re-joined before being passed to embed_batch.
    passed_records = mock_embed.call_args[0][0]
    assert passed_records[0]["content"] == "Hello world this is a long enough post body"
    mock_save.assert_called_once()
    assert out_path == embeddings_dir / "linkedin_gemini_20260101T000000Z.npy"


def test_run_embeddings_applies_limit(tmp_path):
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    raw_dir.mkdir()
    processed_dir.mkdir()

    (raw_dir / "linkedin_20260101T000000Z.json").write_text(
        json.dumps(
            [
                make_raw_post("1", "first post body long enough to pass filter"),
                make_raw_post("2", "second post body long enough to pass filter"),
            ]
        )
    )
    jsonl_path = processed_dir / "linkedin_20260101T000000Z.jsonl"
    jsonl_path.write_text(
        json.dumps({"post_id": "1", "word_count": 9}) + "\n" + json.dumps({"post_id": "2", "word_count": 9}) + "\n"
    )

    settings = make_settings(str(raw_dir))
    fake_vectors = np.zeros((1, 3072), dtype=np.float32)

    with patch("processors.run_embeddings.embed_batch", return_value=(fake_vectors, 0)) as mock_embed, patch(
        "processors.run_embeddings.save_embeddings"
    ):
        run_embeddings(processed_file=str(jsonl_path), settings=settings, limit=1)

    passed_records = mock_embed.call_args[0][0]
    assert len(passed_records) == 1
    assert passed_records[0]["post_id"] == "1"
