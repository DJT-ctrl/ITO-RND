"""Unit tests for processors/profile_sources.py (loading saved profile scrapes
for the optional --with-profile-enrichment pipeline path)."""

import json
from pathlib import Path

import pytest

from processors.profile_sources import (
    extract_scan_timestamp,
    find_paired_profile_file,
    load_profile_lookup_from_post_scan,
    load_profile_records,
)


def test_loads_explicit_profile_file(tmp_path):
    profile_file = tmp_path / "linkedin_profiles_20260101T000000Z.json"
    profile_file.write_text(json.dumps([{"publicIdentifier": "alice", "followerCount": 100}]))

    records = load_profile_records(str(profile_file), str(tmp_path))

    assert records == [{"publicIdentifier": "alice", "followerCount": 100}]


def test_loads_latest_profile_file_when_none_given(tmp_path):
    (tmp_path / "linkedin_profiles_20260101T000000Z.json").write_text(
        json.dumps([{"publicIdentifier": "old"}])
    )
    (tmp_path / "linkedin_profiles_20260102T000000Z.json").write_text(
        json.dumps([{"publicIdentifier": "newest"}])
    )

    records = load_profile_records(None, str(tmp_path))

    assert records == [{"publicIdentifier": "newest"}]


def test_raises_clearly_when_no_profile_file_exists(tmp_path):
    with pytest.raises(ValueError, match="no profile scrape"):
        load_profile_records(None, str(tmp_path))


def test_raises_when_explicit_profile_file_missing(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        load_profile_records(str(tmp_path / "does_not_exist.json"), str(tmp_path))


def test_raises_when_profile_file_is_empty(tmp_path):
    profile_file = tmp_path / "linkedin_profiles_20260101T000000Z.json"
    profile_file.write_text(json.dumps([]))

    with pytest.raises(ValueError, match="no records"):
        load_profile_records(str(profile_file), str(tmp_path))


def test_extract_scan_timestamp_from_post_file():
    assert extract_scan_timestamp("linkedin_20260710T191600Z.json") == "20260710T191600Z"
    assert extract_scan_timestamp(Path("data/raw/linkedin_20260710T191600Z.json")) == "20260710T191600Z"
    assert extract_scan_timestamp("linkedin_2026-07-10_191600Z.json") == "2026-07-10_191600Z"
    assert extract_scan_timestamp("linkedin_profiles_20260710T191600Z.json") is None


def test_find_paired_profile_file_by_timestamp(tmp_path):
    post = tmp_path / "linkedin_20260710T191600Z.json"
    post.write_text("[]")
    profile = tmp_path / "linkedin_profiles_20260710T191600Z.json"
    profile.write_text(json.dumps([{"publicIdentifier": "alice"}]))
    (tmp_path / "linkedin_profiles_20260101T000000Z.json").write_text("[]")

    assert find_paired_profile_file(post, str(tmp_path)) == profile


def test_find_paired_profile_file_falls_back_to_latest(tmp_path):
    post = tmp_path / "linkedin_20260710T191600Z.json"
    post.write_text("[]")
    latest = tmp_path / "linkedin_profiles_20260102T000000Z.json"
    latest.write_text("[]")
    (tmp_path / "linkedin_profiles_20260101T000000Z.json").write_text("[]")

    assert find_paired_profile_file(post, str(tmp_path)) == latest


def test_load_profile_lookup_from_post_scan(tmp_path):
    post = tmp_path / "linkedin_20260710T191600Z.json"
    post.write_text("[]")
    profile = tmp_path / "linkedin_profiles_20260710T191600Z.json"
    profile.write_text(
        json.dumps(
            [
                {
                    "publicIdentifier": "alice",
                    "followerCount": 1200,
                    "industryName": "Tech",
                }
            ]
        )
    )

    lookup, path = load_profile_lookup_from_post_scan(post, str(tmp_path))

    assert path == profile
    assert lookup["alice"]["author_followers"] == 1200
    assert lookup["alice"]["author_industry"] == "Tech"
