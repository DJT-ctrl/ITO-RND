"""Unit tests for storage/pipeline_registry.py."""

import json

import pytest

from storage.pipeline_registry import (
    dedupe_records_by_post_id,
    join_content_to_records,
    list_bundles,
    load_posts_from_scans,
    register_analysed_bundle,
    register_scrape_bundle,
    write_artefact_meta,
)


@pytest.fixture(autouse=True)
def isolated_manifest(tmp_path, monkeypatch):
    manifest = tmp_path / "pipeline_manifest.json"
    monkeypatch.setattr("storage.pipeline_registry._MANIFEST_PATH", manifest)
    monkeypatch.setattr("storage.pipeline_registry._PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr("storage.pipeline_registry._EMBEDDINGS_DIR", tmp_path / "embeddings")
    (tmp_path / "processed").mkdir()
    (tmp_path / "embeddings").mkdir()
    yield manifest


def test_register_scrape_and_analysed_chain():
    register_scrape_bundle(
        bundle_id="2026-07-10_120000Z",
        source_scans=["linkedin_20260710T120000Z.json"],
        source_profiles=["linkedin_profiles_20260710T120000Z.json"],
        post_count=5,
    )
    register_analysed_bundle(
        bundle_id="2026-07-10_120000Z",
        source_scans=["linkedin_20260710T120000Z.json"],
        analysed_jsonl="linkedin_analysed_2026-07-10_120000Z.jsonl",
        analysed_csv="linkedin_analysed_2026-07-10_120000Z.csv",
        with_gemini=True,
        post_count=5,
    )
    bundles = list_bundles(min_stage="analysed", require_gemini=True)
    assert len(bundles) == 1
    assert bundles[0].stage() == "analysed"
    assert bundles[0].source_scans == ["linkedin_20260710T120000Z.json"]


def test_dedupe_records_by_post_id():
    records = [{"post_id": "1", "x": 1}, {"post_id": "1", "x": 2}, {"post_id": "2"}]
    assert len(dedupe_records_by_post_id(records)) == 2


def test_load_posts_from_scans(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "a.json").write_text(json.dumps([{"id": "1", "content": "hello"}]))
    posts = load_posts_from_scans(["a.json"], raw_data_dir=str(raw))
    assert len(posts) == 1


def test_join_content_scoped_to_source_scans(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "scan1.json").write_text(json.dumps([{"id": "1", "content": "from scan1"}]))
    (raw / "scan2.json").write_text(json.dumps([{"id": "2", "content": "from scan2"}]))
    records = [{"post_id": "1"}, {"post_id": "2"}]
    joined = join_content_to_records(records, source_scans=["scan1.json"], raw_data_dir=str(raw))
    assert joined[0]["content"] == "from scan1"
    assert joined[1]["content"] == ""


def test_write_artefact_meta(tmp_path):
    artefact = tmp_path / "linkedin_analysed_test.jsonl"
    artefact.write_text("{}\n")
    meta_path = write_artefact_meta(artefact, {"bundle_id": "test"})
    assert meta_path.name == "linkedin_analysed_test.jsonl.meta.json"
