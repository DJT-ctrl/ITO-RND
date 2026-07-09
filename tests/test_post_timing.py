"""Unit tests for processors/post_timing.py (local posting-time inference)."""

from processors.post_timing import build_post_timing_fields, infer_timezone_from_location

# 1783081190913 == 2026-07-03T12:19:50.913Z (Friday, per repo real data).
_TS = 1783081190913


# ── infer_timezone_from_location ─────────────────────────────────────────────

def test_infer_timezone_exact_suffix_match():
    assert infer_timezone_from_location("Barcelona, Catalonia, Spain") == "Europe/Madrid"


def test_infer_timezone_california_suffix():
    assert infer_timezone_from_location("Long Beach, California, United States") == "America/Los_Angeles"
    assert infer_timezone_from_location("San Francisco, California, United States") == "America/Los_Angeles"


def test_infer_timezone_metro_area_alias():
    assert infer_timezone_from_location("Washington DC-Baltimore Area") == "America/New_York"


def test_infer_timezone_india_city_suffix():
    assert infer_timezone_from_location("Bengaluru, Karnataka, India") == "Asia/Kolkata"
    assert infer_timezone_from_location("Delhi, India") == "Asia/Kolkata"


def test_infer_timezone_uk_suffix():
    assert infer_timezone_from_location("Reigate, England, United Kingdom") == "Europe/London"


def test_infer_timezone_nigeria_suffix():
    assert infer_timezone_from_location("Abuja, Federal Capital Territory, Nigeria") == "Africa/Lagos"


def test_infer_timezone_returns_none_for_ambiguous_country_only():
    # "United States" alone is deliberately NOT in the safe country table —
    # multiple timezones, guessing would silently poison timing analysis.
    assert infer_timezone_from_location("United States") is None


def test_infer_timezone_returns_none_for_unknown_location():
    assert infer_timezone_from_location("Somewhere, Nowhereland") is None


def test_infer_timezone_returns_none_for_empty_or_missing():
    assert infer_timezone_from_location("") is None
    assert infer_timezone_from_location(None) is None


# ── build_post_timing_fields ─────────────────────────────────────────────────

def test_build_post_timing_fields_no_timestamp_returns_all_none():
    result = build_post_timing_fields(None, "Europe/Madrid")
    assert result == {"hour_of_day": None, "day_of_week": None, "author_timezone": None}


def test_build_post_timing_fields_falls_back_to_utc_when_no_timezone():
    result = build_post_timing_fields(_TS, None)
    assert result["author_timezone"] is None
    assert result["hour_of_day"] == 12  # 2026-07-03T12:19:50.913Z
    assert result["day_of_week"] == "Friday"


def test_build_post_timing_fields_uses_resolved_local_timezone():
    result = build_post_timing_fields(_TS, "America/Los_Angeles")
    assert result["author_timezone"] == "America/Los_Angeles"
    assert result["hour_of_day"] == 5  # UTC 12:19 -> PDT 05:19
    assert result["day_of_week"] == "Friday"


def test_build_post_timing_fields_falls_back_to_utc_for_unknown_timezone_name():
    result = build_post_timing_fields(_TS, "Not/ARealZone")
    assert result["author_timezone"] is None
    assert result["hour_of_day"] == 12
