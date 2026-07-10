"""Persists analysed feature records to timestamped CSV and/or JSONL files.

Intentionally separate from SampleStore (which handles raw JSON) so the
two stores stay independently swappable — raw storage and processed storage
may need to diverge (e.g. a database for processed data) without touching
each other's code.

Two output formats are supported side by side, not as alternatives:
  save()       — CSV. Easy to eyeball in a spreadsheet or Streamlit table.
  save_jsonl() — JSON Lines (one JSON object per line). The format Erdal's
                 plan expects as input to the T1.3 embedding engine.
Both are written for every pipeline run (see processors/run_pipeline.py)
so neither use case is left without the format it needs.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from config.paths import resolve_data_path, utc_artifact_stamp


class ProcessedStore:
    def __init__(self, base_dir: str = "data/processed"):
        self._base_dir = resolve_data_path(base_dir)

    def save(
        self,
        platform: str,
        records: list[dict],
        *,
        timestamp: str | None = None,
    ) -> Path:
        """Write records to a timestamped CSV and return its path."""
        if not records:
            raise ValueError("records list is empty — nothing to save.")
        self._base_dir.mkdir(parents=True, exist_ok=True)
        if timestamp is None:
            timestamp = utc_artifact_stamp()
        file_path = self._base_dir / f"{platform}_{timestamp}.csv"
        with file_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=records[0].keys())
            writer.writeheader()
            writer.writerows(records)
        return file_path

    def save_jsonl(
        self,
        platform: str,
        records: list[dict],
        *,
        timestamp: str | None = None,
    ) -> Path:
        """Write records to a timestamped JSON Lines file and return its path.

        Each line is one standalone JSON object, which is what batch
        embedding pipelines (T1.3) typically expect to stream line-by-line
        without loading the whole dataset into memory at once.
        """
        if not records:
            raise ValueError("records list is empty — nothing to save.")
        self._base_dir.mkdir(parents=True, exist_ok=True)
        if timestamp is None:
            timestamp = utc_artifact_stamp()
        file_path = self._base_dir / f"{platform}_{timestamp}.jsonl"
        with file_path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return file_path
