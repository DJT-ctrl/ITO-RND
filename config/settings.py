"""Central place to load run configuration from environment variables.

Nothing else in the project should call `os.getenv` directly - every module
reads config through a `Settings` instance so there's exactly one place to
change how configuration is sourced later (e.g. a secrets manager).
"""

import json
import os
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

load_dotenv()


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


def load_settings() -> Settings:
    load_dotenv(override=True)
    return Settings(
        apify_api_token=os.getenv("APIFY_API_TOKEN", ""),
        apify_actor_id=os.getenv("APIFY_ACTOR_ID", ""),
        apify_profile_actor_id=os.getenv("APIFY_PROFILE_ACTOR_ID", ""),
        linkedin_cookies=_parse_cookies(os.getenv("LINKEDIN_COOKIES", "")),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        raw_data_dir=os.getenv("RAW_DATA_DIR", "data/raw"),
        default_search_limit=int(os.getenv("DEFAULT_SEARCH_LIMIT", "20")),
        database_url=os.getenv("DATABASE_URL", ""),
    )


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
