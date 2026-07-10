"""Persists raw scraper output untouched, one timestamped file per run.

This module has no knowledge of *which* platform produced the samples - it
just writes whatever list[dict] it's given. Making sense of the data (trend
detection, tagging, OCR, etc.) is a separate future pipeline stage, kept out
of this module on purpose so storage stays dumb and reusable across
platforms.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config.paths import resolve_data_path, utc_artifact_stamp


class SampleStore:
    def __init__(self, base_dir: str = "data/raw"):
        self._base_dir = resolve_data_path(base_dir)

    def save(
        self,
        platform: str,
        samples: list[dict[str, Any]],
        *,
        timestamp: str | None = None,
    ) -> Path:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        if timestamp is None:
            timestamp = utc_artifact_stamp()
        file_path = self._base_dir / f"{platform}_{timestamp}.json"
        file_path.write_text(json.dumps(samples, indent=2, ensure_ascii=False))
        return file_path
