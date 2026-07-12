"""Central place to load run configuration from environment variables.

Nothing else in the project should call `os.getenv` directly - every module
reads config through a `Settings` instance so there's exactly one place to
change how configuration is sourced later (e.g. a secrets manager).
"""

import json
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from dotenv import load_dotenv

from config.paths import PROJECT_ROOT, project_root, resolve_data_path, utc_artifact_stamp

# Re-export path helpers for older imports (prefer config.paths in new code).
__all__ = [
    "AGENT_GEMINI_MODEL",
    "GEMINI_MODEL",
    "PYDANTIC_AI_GEMINI_MODEL",
    "Settings",
    "load_settings",
    "project_root",
    "pydantic_ai_gemini_model",
    "resolve_data_path",
    "sync_google_api_key",
    "utc_artifact_stamp",
]

# Always load repo-root .env regardless of Streamlit/shell working directory.
_PROJECT_ROOT = PROJECT_ROOT
load_dotenv(_PROJECT_ROOT / ".env")

# google-genai model id (post_analyser, embedder, etc.)
GEMINI_MODEL = "gemini-2.5-flash-lite"

# pydantic-ai evaluation agents — full flash by default for reasoning quality;
# override with AGENT_GEMINI_MODEL in .env to match GEMINI_MODEL if you want.
AGENT_GEMINI_MODEL = os.getenv("AGENT_GEMINI_MODEL", "gemini-2.5-flash")


def pydantic_ai_gemini_model(model_id: Optional[str] = None) -> str:
    """Format a Gemini model id for pydantic-ai's Google GLA provider."""
    raw = model_id or AGENT_GEMINI_MODEL
    if raw.startswith("google-gla:"):
        return raw
    if raw.startswith("google:"):
        raw = raw.split(":", 1)[1]
    return f"google-gla:{raw}"


PYDANTIC_AI_GEMINI_MODEL = pydantic_ai_gemini_model()


def sync_google_api_key() -> None:
    """pydantic-ai's Google provider reads GOOGLE_API_KEY — mirror GEMINI_API_KEY."""
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        os.environ.setdefault("GOOGLE_API_KEY", gemini_key)


sync_google_api_key()


@dataclass(frozen=True)
class Settings:
    apify_api_token: str
    apify_actor_id: str
    apify_profile_actor_id: str
    # Exported via the Cookie-Editor extension (JSON array of cookie objects).
    # Treat as a credential: never log it, never include it in error messages.
    linkedin_cookies: list[dict[str, Any]]
    gemini_api_key: str
    raw_data_dir: str
    default_search_limit: int
    # T1.4/T1.5: Postgres+pgvector connection. A single DSN string (rather
    # than separate host/port/user fields) because that's exactly what
    # psycopg.connect() accepts directly. Empty by default so anything not
    # touching the database still runs without a .env change.
    database_url: str = ""
    # Tier 1 discoverability: corpus-grounded SEO (default) or gemini_only baseline.
    seo_discoverability_mode: str = "corpus"
    corpus_benchmark_ttl_hours: int = 24
    # Tier 2 discoverability: Google Trends via pytrends (opt-in; off by default).
    google_trends_enabled: bool = False
    google_trends_cache_ttl_hours: int = 12
    google_trends_geo: str = ""
    # T6.6: re-scrape cached author profiles after this many days.
    profile_cache_staleness_days: int = 30
    # Prediction validation pipeline (validation_pipeline/).
    validation_window_hours: int = 48
    validation_dev_window_minutes: Optional[int] = None
    validation_max_posts_per_run: int = 20
    validation_min_post_age_hours: int = 0
    validation_data_dir: str = "data/validation"
    # Profile fallback depth when direct post-URL re-scrape returns no items.
    validation_rescrape_profile_max_posts: int = 100
    # harvestapi/linkedin-profile-posts — direct post URL re-scrape for validation.
    apify_post_url_actor_id: str = "harvestapi/linkedin-profile-posts"
    # Evaluation-cycle telemetry (telemetry/).
    telemetry_data_dir: str = "data/telemetry"
    eval_cost_warning_usd: float = 0.10
    eval_latency_warning_ms: int = 60000
    eval_step_latency_warning_ms: int = 20000

    def validation_window(self) -> timedelta:
        """Delay between post publish time and scheduled re-scrape validation."""
        if self.validation_dev_window_minutes is not None:
            return timedelta(minutes=self.validation_dev_window_minutes)
        return timedelta(hours=self.validation_window_hours)


def load_settings() -> Settings:
    load_dotenv(_PROJECT_ROOT / ".env", override=True)
    sync_google_api_key()
    return Settings(
        apify_api_token=os.getenv("APIFY_API_TOKEN", ""),
        apify_actor_id=os.getenv("APIFY_ACTOR_ID", ""),
        apify_profile_actor_id=os.getenv("APIFY_PROFILE_ACTOR_ID", ""),
        apify_post_url_actor_id=os.getenv(
            "APIFY_POST_URL_ACTOR_ID", "harvestapi/linkedin-profile-posts"
        ),
        linkedin_cookies=_parse_cookies(os.getenv("LINKEDIN_COOKIES", "")),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        raw_data_dir=os.getenv("RAW_DATA_DIR", "data/raw"),
        default_search_limit=int(os.getenv("DEFAULT_SEARCH_LIMIT", "20")),
        database_url=os.getenv("DATABASE_URL", ""),
        seo_discoverability_mode=os.getenv("SEO_DISCOVERABILITY_MODE", "corpus"),
        corpus_benchmark_ttl_hours=int(os.getenv("CORPUS_BENCHMARK_TTL_HOURS", "24")),
        google_trends_enabled=_env_bool("GOOGLE_TRENDS_ENABLED", default=False),
        google_trends_cache_ttl_hours=int(os.getenv("GOOGLE_TRENDS_CACHE_TTL_HOURS", "12")),
        google_trends_geo=os.getenv("GOOGLE_TRENDS_GEO", ""),
        profile_cache_staleness_days=int(os.getenv("PROFILE_CACHE_STALENESS_DAYS", "30")),
        validation_window_hours=int(os.getenv("VALIDATION_WINDOW_HOURS", "48")),
        validation_dev_window_minutes=_env_optional_int("VALIDATION_DEV_WINDOW_MINUTES"),
        validation_max_posts_per_run=int(os.getenv("VALIDATION_MAX_POSTS_PER_RUN", "20")),
        validation_min_post_age_hours=int(os.getenv("VALIDATION_MIN_POST_AGE_HOURS", "0")),
        validation_data_dir=os.getenv("VALIDATION_DATA_DIR", "data/validation"),
        validation_rescrape_profile_max_posts=int(
            os.getenv("VALIDATION_RESCRAPE_PROFILE_MAX_POSTS", "100")
        ),
        telemetry_data_dir=os.getenv("TELEMETRY_DATA_DIR", "data/telemetry"),
        eval_cost_warning_usd=float(os.getenv("EVAL_COST_WARNING_USD", "0.10")),
        eval_latency_warning_ms=int(os.getenv("EVAL_LATENCY_WARNING_MS", "60000")),
        eval_step_latency_warning_ms=int(os.getenv("EVAL_STEP_LATENCY_WARNING_MS", "20000")),
    )


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_optional_int(name: str) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return int(raw)


def _parse_cookies(raw: str) -> list[dict[str, Any]]:
    """Parse LINKEDIN_COOKIES (a JSON array exported via Cookie-Editor).

    Returns an empty list if unset so the app still starts without it; the
    profile scraper raises its own clear error if it's needed but missing.
    """
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        # Deliberately don't include `raw` in the message - it's a credential.
        raise ValueError(
            "LINKEDIN_COOKIES is not valid JSON. Export cookies with the "
            "Cookie-Editor extension and paste the full JSON array into .env."
        ) from exc
