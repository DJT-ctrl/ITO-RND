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

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


class ProcessedStore:
    def __init__(self, base_dir: str = "data/processed"):
        self._base_dir = Path(base_dir)

    def save(self, platform: str, records: list[dict]) -> Path:
        """Write records to a timestamped CSV and return its path."""
        if not records:
            raise ValueError("records list is empty — nothing to save.")
        self._base_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        file_path = self._base_dir / f"{platform}_{timestamp}.csv"
        with file_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=records[0].keys())
            writer.writeheader()
            writer.writerows(records)
        return file_path

    def save_jsonl(self, platform: str, records: list[dict]) -> Path:
        """Write records to a timestamped JSON Lines file and return its path.

        Each line is one standalone JSON object, which is what batch
        embedding pipelines (T1.3) typically expect to stream line-by-line
        without loading the whole dataset into memory at once.
        """
        if not records:
            raise ValueError("records list is empty — nothing to save.")
        self._base_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        file_path = self._base_dir / f"{platform}_{timestamp}.jsonl"
        with file_path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return file_path
