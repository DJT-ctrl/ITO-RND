"""Unit tests for processors/run_db_ingest.py (dashboard auto-ingest path)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from processors.run_db_ingest import ingest_embedded_records, run_db_ingest


def test_ingest_embedded_records_upserts_and_registers():
    settings = MagicMock()
    settings.database_url = "postgresql://ito:x@localhost/ito_posts"
    records = [{"post_id": "a", "content": "hello world here"}, {"post_id": "b", "content": "more words ok"}]
    vectors = np.zeros((2, 4), dtype=np.float32)

    conn = MagicMock()
    with patch("processors.run_db_ingest.get_connection", return_value=conn) as mock_conn, patch(
        "processors.run_db_ingest.create_schema"
    ) as mock_schema, patch(
        "processors.run_db_ingest.insert_posts", return_value=2
    ) as mock_insert, patch(
        "processors.run_db_ingest.register_ingest_bundle"
    ) as mock_register:
        count = ingest_embedded_records(
            records,
            vectors,
            settings=settings,
            bundle_id="2026-07-27_210530Z",
            skip_backup=True,
        )

    assert count == 2
    mock_conn.assert_called_once_with(settings)
    mock_schema.assert_called_once_with(conn)
    mock_insert.assert_called_once()
    mock_register.assert_called_once_with(bundle_id="2026-07-27_210530Z", ingested_count=2)
    conn.close.assert_called_once()


def test_ingest_embedded_records_requires_database_url():
    settings = MagicMock()
    settings.database_url = ""
    with pytest.raises(ValueError, match="DATABASE_URL"):
        ingest_embedded_records(
            [{"post_id": "a"}],
            np.zeros((1, 2), dtype=np.float32),
            settings=settings,
        )


def test_ingest_embedded_records_rejects_length_mismatch():
    settings = MagicMock()
    settings.database_url = "postgresql://ito:x@localhost/ito_posts"
    with pytest.raises(ValueError, match="length mismatch"):
        ingest_embedded_records(
            [{"post_id": "a"}, {"post_id": "b"}],
            np.zeros((1, 2), dtype=np.float32),
            settings=settings,
        )


def test_run_db_ingest_skips_backup_when_compose_db_down(tmp_path):
    settings = MagicMock()
    settings.database_url = "postgresql://ito:x@localhost/ito_posts"
    jsonl = tmp_path / "posts.jsonl"
    jsonl.write_text(
        '{"post_id":"1","content":"ten words make this eligible for embed filter","word_count":10}\n'
    )
    npy = tmp_path / "vecs.npy"
    np.save(npy, np.zeros((1, 3), dtype=np.float32))

    with patch(
        "processors.run_db_ingest.create_backup",
        side_effect=RuntimeError('pg_dump failed (exit 1): service "db" is not running'),
    ), patch(
        "processors.run_db_ingest.load_and_join",
        return_value=(
            [
                {
                    "post_id": "1",
                    "content": "ten words make this eligible for embed filter",
                    "word_count": 10,
                }
            ],
            jsonl,
            [],
        ),
    ), patch(
        "processors.run_db_ingest.ingest_embedded_records", return_value=1
    ) as mock_ingest, patch(
        "storage.pipeline_registry.bundles_for_analysed_files", return_value=[]
    ):
        count = run_db_ingest(
            processed_file=str(jsonl),
            embeddings_file=str(npy),
            settings=settings,
            skip_backup=False,
        )

    assert count == 1
    mock_ingest.assert_called_once()
