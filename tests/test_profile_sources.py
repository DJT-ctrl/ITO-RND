"""Unit tests for processors/profile_sources.py (loading saved profile scrapes
for the optional --with-profile-enrichment pipeline path)."""

import json

import pytest

from processors.profile_sources import load_profile_records


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
