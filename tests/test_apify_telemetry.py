"""Unit tests for Apify cost telemetry."""

from __future__ import annotations


import pytest

from config.settings import Settings
from telemetry.apify import (
    apify_run_record_from_response,
    load_apify_runs,
    save_apify_run,
    summarize_apify_runs,
)


def make_settings(tmp_path, **overrides) -> Settings:
    defaults = dict(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="",
        raw_data_dir="data/raw",
        default_search_limit=10,
        telemetry_data_dir=str(tmp_path / "telemetry"),
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_apify_run_record_from_response_extracts_cost():
    run = {
        "id": "run-xyz",
        "status": "SUCCEEDED",
        "usageTotalUsd": 0.87,
        "stats": {"computeUnits": 2.1},
        "startedAt": "2026-07-12T12:00:00.000Z",
        "finishedAt": "2026-07-12T12:02:00.000Z",
    }
    record = apify_run_record_from_response(
        run,
        actor_id="harvestapi/linkedin-post-search",
        scraper="linkedin_posts",
        item_count=25,
        context="collection:test",
    )
    assert record.run_id == "run-xyz"
    assert record.cost_usd == pytest.approx(0.87)
    assert record.compute_units == pytest.approx(2.1)
    assert record.item_count == 25


def test_save_and_load_apify_runs_jsonl(tmp_path):
    settings = make_settings(tmp_path)
    record = apify_run_record_from_response(
        {"id": "a", "status": "SUCCEEDED", "usageTotalUsd": 0.5, "stats": {}},
        actor_id="actor-a",
        scraper="linkedin_posts",
        item_count=10,
    )
    save_apify_run(record, settings)
    loaded = load_apify_runs(settings)
    assert len(loaded) == 1
    assert loaded[0].cost_usd == pytest.approx(0.5)


def test_summarize_apify_runs_splits_by_scraper():
    post = apify_run_record_from_response(
        {"id": "1", "status": "SUCCEEDED", "usageTotalUsd": 0.3, "stats": {}},
        actor_id="post-actor",
        scraper="linkedin_posts",
        item_count=5,
    )
    profile = apify_run_record_from_response(
        {"id": "2", "status": "SUCCEEDED", "usageTotalUsd": 0.7, "stats": {}},
        actor_id="profile-actor",
        scraper="linkedin_profiles",
        item_count=3,
    )
    summary = summarize_apify_runs([post, profile])
    assert summary.total_cost_usd == pytest.approx(1.0)
    assert summary.post_search_cost_usd == pytest.approx(0.3)
    assert summary.profile_scrape_cost_usd == pytest.approx(0.7)
