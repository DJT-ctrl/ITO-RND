"""Project config package — re-exports for stable imports under Streamlit hot-reload."""

from config.paths import PROJECT_ROOT, project_root, resolve_data_path, utc_artifact_stamp
from config.settings import (
    AGENT_GEMINI_MODEL,
    GEMINI_MODEL,
    PYDANTIC_AI_GEMINI_MODEL,
    Settings,
    load_settings,
    pydantic_ai_gemini_model,
    sync_google_api_key,
)

__all__ = [
    "AGENT_GEMINI_MODEL",
    "GEMINI_MODEL",
    "PROJECT_ROOT",
    "PYDANTIC_AI_GEMINI_MODEL",
    "Settings",
    "load_settings",
    "project_root",
    "pydantic_ai_gemini_model",
    "resolve_data_path",
    "sync_google_api_key",
    "utc_artifact_stamp",
]
