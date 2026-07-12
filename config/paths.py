"""Repo-root path helpers — separate from settings so Streamlit hot-reload
does not serve a stale cached settings module missing newly added names."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TELEMETRY_DATA_DIR = "data/telemetry"


def project_root() -> Path:
    return PROJECT_ROOT


def resolve_data_path(relative_or_absolute: str) -> Path:
    """Resolve data/* paths from the repo root so Streamlit cwd never matters."""
    path = Path(relative_or_absolute)
    return path if path.is_absolute() else PROJECT_ROOT / path


def resolve_telemetry_data_dir(settings: object) -> Path:
    """Telemetry storage dir; getattr fallback tolerates stale Settings under hot-reload."""
    raw = getattr(settings, "telemetry_data_dir", DEFAULT_TELEMETRY_DATA_DIR)
    return resolve_data_path(str(raw))


def utc_artifact_stamp() -> str:
    """Human-readable UTC stamp for saved files, e.g. 2026-07-10_204537Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%SZ")
