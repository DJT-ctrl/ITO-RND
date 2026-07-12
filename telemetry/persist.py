"""Telemetry persistence — file backend now, Postgres stub for production."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional, Protocol

from config.paths import DEFAULT_TELEMETRY_DATA_DIR, resolve_data_path, utc_artifact_stamp
from config.settings import Settings
from telemetry.schemas import RunMetadata

logger = logging.getLogger(__name__)

# Future production schema (not applied yet):
# CREATE TABLE evaluation_runs (
#     run_id          UUID PRIMARY KEY,
#     user_id         TEXT,
#     started_at      TIMESTAMPTZ NOT NULL,
#     ended_at        TIMESTAMPTZ,
#     total_cost_usd  DOUBLE PRECISION,
#     total_latency_ms DOUBLE PRECISION,
#     run_metadata    JSONB NOT NULL,
#     created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
# );
# CREATE INDEX evaluation_runs_user_started_idx ON evaluation_runs (user_id, started_at DESC);


class TelemetryBackend(Protocol):
    def save(self, metadata: RunMetadata) -> Optional[Path]: ...


class FileTelemetryBackend:
    """Write one JSON file per evaluation cycle."""

    def __init__(self, data_dir: str) -> None:
        self._data_dir = resolve_data_path(data_dir)

    def save(self, metadata: RunMetadata) -> Optional[Path]:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        stamp = utc_artifact_stamp()
        short_id = metadata.run_id[:8]
        path = self._data_dir / f"eval_{stamp}_{short_id}.json"
        try:
            payload = metadata.model_dump(mode="json")
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return path
        except OSError as exc:
            logger.warning("Failed to persist telemetry to %s: %s", path, exc)
            return None


class PostgresTelemetryBackend:
    """Stub for future user-linked evaluation run storage."""

    def save(self, metadata: RunMetadata, conn: Any = None) -> None:
        raise NotImplementedError(
            "PostgresTelemetryBackend is not wired yet — use FileTelemetryBackend"
        )


def save_run_metadata(metadata: RunMetadata, settings: Settings) -> Optional[Path]:
    """Persist run metadata; failures are logged, never raised."""
    backend = FileTelemetryBackend(
        getattr(settings, "telemetry_data_dir", DEFAULT_TELEMETRY_DATA_DIR)
    )
    return backend.save(metadata)
