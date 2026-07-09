"""Infers an author's local posting time from their profile location text.

Why this exists
-----------------
Stage 1 (processors/post_analyser.py) has always derived `hour_of_day`/
`day_of_week` from the raw UTC `postedAt` timestamp. That's the AUTHOR'S
platform-recorded moment, but LinkedIn feed timing patterns ("best time to
post") only make sense in the author's OWN local time — 9am UTC is a very
different "hour of day" for someone in Los Angeles vs. Mumbai.

This is opt-in (see processors/run_pipeline.py's --with-profile-enrichment):
only enriched posts carry a resolvable `author_location_text`, so the
non-enriched path is completely unaffected by this module.

Design
-------
Stdlib only (`zoneinfo`), no new dependency. A tiny, deliberately small
mapping table — exact/suffix matches on normalized location text, with a
narrow "safe" country-level fallback (only for countries that are, in
practice, a single timezone). Ambiguous multi-timezone countries (US,
Canada, Australia, Brazil, Russia...) are NEVER guessed from country alone
here; they only resolve via the more specific city/region suffix entries.

Returns None (never a wrong guess) whenever a location can't be confidently
mapped — callers fall back to UTC, exactly like this feature never
happened.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Suffix-matched first (longest match wins), so "Barcelona, Catalonia,
# Spain" matches "catalonia, spain" even though the exact city isn't
# listed. Add new entries here as real location text is observed.
_SUFFIX_TIMEZONES: dict[str, str] = {
    "catalonia, spain": "Europe/Madrid",
    "california, united states": "America/Los_Angeles",
    "washington dc-baltimore area": "America/New_York",
    "england, united kingdom": "Europe/London",
    "federal capital territory, nigeria": "Africa/Lagos",
    "karnataka, india": "Asia/Kolkata",
    "delhi, india": "Asia/Kolkata",
}

# Only countries that are safely a single timezone in practice — deliberately
# excludes the US/Canada/Australia/Brazil/Russia/etc. multi-timezone cases.
_COUNTRY_TIMEZONES: dict[str, str] = {
    "spain": "Europe/Madrid",
    "india": "Asia/Kolkata",
    "united kingdom": "Europe/London",
    "nigeria": "Africa/Lagos",
}


def _normalize(location_text: str) -> str:
    return " ".join(location_text.split()).strip().lower()


def infer_timezone_from_location(location_text: Optional[str]) -> Optional[str]:
    """Return an IANA timezone name inferred from `location_text`, or None
    if it can't be confidently resolved.

    Matching order: exact/suffix table first (most specific), then a
    country-only fallback restricted to single-timezone countries. Never
    guesses for ambiguous multi-timezone countries.
    """
    if not location_text:
        return None
    normalized = _normalize(location_text)

    for suffix, tz_name in _SUFFIX_TIMEZONES.items():
        if normalized == suffix or normalized.endswith(suffix):
            return tz_name

    for country, tz_name in _COUNTRY_TIMEZONES.items():
        if normalized == country or normalized.endswith(f", {country}"):
            return tz_name

    return None


def build_post_timing_fields(
    timestamp_ms: Optional[int], timezone_name: Optional[str]
) -> dict[str, Any]:
    """Return `hour_of_day`/`day_of_week` in `timezone_name` when resolvable,
    falling back to UTC (today's behavior) otherwise. Always also returns
    `author_timezone` so callers/downstream can see what was actually used
    (None when no location-derived timezone applied).

    A `timezone_name` that zoneinfo doesn't recognise is treated the same
    as None — falls back to UTC rather than raising, since a single bad/
    unexpected timezone string should never crash a batch run.
    """
    if not timestamp_ms:
        return {"hour_of_day": None, "day_of_week": None, "author_timezone": None}

    resolved_tz: Optional[ZoneInfo] = None
    if timezone_name:
        try:
            resolved_tz = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            resolved_tz = None

    posted_dt = datetime.fromtimestamp(
        timestamp_ms / 1000, tz=resolved_tz or timezone.utc
    )
    return {
        "hour_of_day": posted_dt.hour,
        "day_of_week": posted_dt.strftime("%A"),
        "author_timezone": timezone_name if resolved_tz else None,
    }
