"""Unit tests for telemetry package."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from config.settings import Settings
from telemetry.collector import RunMetadataCollector
from telemetry.persist import FileTelemetryBackend
from telemetry.pricing import cost_from_llm_usage, cost_from_tokens, get_model_rates
from telemetry.schemas import RunMetadata, StepTelemetry
from telemetry.thresholds import evaluate_thresholds


def make_settings(**overrides) -> Settings:
    defaults = dict(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="test-key",
        raw_data_dir="data/raw",
        default_search_limit=10,
        eval_cost_warning_usd=0.10,
        eval_latency_warning_ms=60000,
        eval_step_latency_warning_ms=20000,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_cost_from_tokens_uses_model_rates():
    cost = cost_from_tokens("gemini-embedding-001", input_tokens=1_000_000)
    assert cost == pytest.approx(0.025)


def test_cost_from_llm_usage_reads_pydantic_ai_shape():
    usage = SimpleNamespace(input_tokens=1000, output_tokens=500)
    input_tokens, output_tokens, cost = cost_from_llm_usage("gemini-2.5-flash", usage)
    assert input_tokens == 1000
    assert output_tokens == 500
    assert cost > 0


def test_collector_aggregates_steps_and_finalize():
    settings = make_settings()
    collector = RunMetadataCollector(settings=settings, agent_model="google-gla:gemini-2.5-flash")
    now = datetime.now(timezone.utc)
    collector.record_step(
        step_id="agent.predictor",
        label="Predictor",
        stage="agent",
        call_type="llm",
        latency_ms=1200.0,
        started_at=now,
        ended_at=now,
        model="gemini-2.5-flash",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.001,
    )
    metadata = collector.finalize()
    assert metadata.total_input_tokens == 100
    assert metadata.total_output_tokens == 50
    assert metadata.total_cost_usd == pytest.approx(0.001)
    assert len(metadata.steps) == 1
    assert metadata.agent_model == "google-gla:gemini-2.5-flash"


def test_evaluate_thresholds_flags_cost_and_latency():
    settings = make_settings(
        eval_cost_warning_usd=0.05,
        eval_latency_warning_ms=1000,
        eval_step_latency_warning_ms=1000,
    )
    now = datetime.now(timezone.utc)
    metadata = RunMetadata(
        run_id="test-run",
        started_at=now,
        ended_at=now,
        total_latency_ms=5000,
        total_cost_usd=0.12,
        total_input_tokens=100,
        total_output_tokens=50,
        steps=[
            StepTelemetry(
                step_id="agent.predictor",
                label="Predictor",
                stage="agent",
                call_type="llm",
                status="ok",
                latency_ms=2500,
                started_at=now,
                ended_at=now,
            )
        ],
    )
    warnings = evaluate_thresholds(metadata, settings)
    codes = {w.code for w in warnings}
    assert "cost_threshold" in codes
    assert "latency_threshold" in codes
    assert "step_latency_threshold" in codes


def test_file_backend_writes_json(tmp_path):
    now = datetime.now(timezone.utc)
    metadata = RunMetadata(
        run_id="abc-123-def",
        started_at=now,
        ended_at=now,
        total_latency_ms=10,
        total_cost_usd=0.01,
        total_input_tokens=1,
        total_output_tokens=1,
        steps=[],
    )
    backend = FileTelemetryBackend(str(tmp_path))
    path = backend.save(metadata)
    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "abc-123-def"
    assert payload["schema_version"] == "1.0"


def test_get_model_rates_normalizes_provider_prefix():
    rates = get_model_rates("google-gla:gemini-2.5-flash")
    assert rates.input_per_1m > 0
