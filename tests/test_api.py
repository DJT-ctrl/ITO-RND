"""Unit tests for api/main.py (T2: FastAPI + cosine-similarity retrieval).

Both embed_query() and find_similar() are patched — no real DB or Gemini
calls in unit tests, per repo convention (see tests/test_embedder.py and
tests/test_vector_store.py).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _stub_discoverability_gather(monkeypatch):
    async def _fake_gather(draft, similar_posts, settings, *, use_google_trends=False, collector=None):
        return None, []

    monkeypatch.setattr("agents.orchestrator._gather_discoverability_context", _fake_gather)


@pytest.fixture(autouse=True)
def _stub_telemetry_persist(monkeypatch):
    monkeypatch.setattr("agents.orchestrator.save_run_metadata", lambda metadata, settings: None)


def fake_row(post_id: str = "1") -> dict:
    return {
        "post_id": post_id,
        "content": "hello world",
        "likes": 10,
        "comments": 2,
        "shares": 1,
        "total_engagement": 13,
        "engagement_percentile": 75.0,
        "engagement_zscore": 0.8,
        "cosine_distance": 0.05,
    }


class _AgentStub:
    def __init__(self, output: dict):
        self._output = output

    async def run(self, prompt: str, deps) -> SimpleNamespace:
        return SimpleNamespace(
            output=self._output,
            usage=lambda: SimpleNamespace(input_tokens=100, output_tokens=50, requests=1),
        )


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("api.main.register_vector")
@patch("api.main.get_connection")
@patch("api.main.find_similar")
@patch("api.main.embed_query")
def test_similar_posts_valid_request(mock_embed_query, mock_find_similar, mock_get_connection, mock_register_vector):
    mock_embed_query.return_value = (np.zeros(3072, dtype=np.float32), 10)
    mock_find_similar.return_value = [fake_row("1"), fake_row("2")]
    mock_get_connection.return_value = MagicMock()

    response = client.post(
        "/api/v1/similar-posts",
        json={"content": "Excited to announce our new backend engineering hire!", "limit": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query_content"] == "Excited to announce our new backend engineering hire!"
    assert len(body["results"]) == 2
    assert body["results"][0]["post_id"] == "1"
    mock_find_similar.assert_called_once()
    assert mock_find_similar.call_args.kwargs["limit"] == 5
    assert mock_find_similar.call_args.kwargs["user_id"] is None


@patch("api.main.register_vector")
@patch("api.main.get_connection")
@patch("api.main.find_similar")
@patch("api.main.embed_query")
def test_similar_posts_forwards_user_id(mock_embed_query, mock_find_similar, mock_get_connection, mock_register_vector):
    mock_embed_query.return_value = (np.zeros(3072, dtype=np.float32), 10)
    mock_find_similar.return_value = [fake_row("1")]
    mock_get_connection.return_value = MagicMock()

    response = client.post(
        "/api/v1/similar-posts",
        json={"content": "Excited to announce our new backend engineering hire!", "user_id": "user-42"},
    )

    assert response.status_code == 200
    assert mock_find_similar.call_args.kwargs["user_id"] == "user-42"


@patch("api.main.get_connection")
@patch("api.main.find_similar")
@patch("api.main.embed_query")
def test_similar_posts_empty_content_rejected(mock_embed_query, mock_find_similar, mock_get_connection):
    response = client.post("/api/v1/similar-posts", json={"content": "", "limit": 5})
    assert response.status_code == 422
    mock_embed_query.assert_not_called()


@patch("api.main.get_connection")
@patch("api.main.find_similar")
@patch("api.main.embed_query")
def test_similar_posts_limit_out_of_range_rejected(mock_embed_query, mock_find_similar, mock_get_connection):
    response = client.post("/api/v1/similar-posts", json={"content": "valid text", "limit": 0})
    assert response.status_code == 422

    response = client.post("/api/v1/similar-posts", json={"content": "valid text", "limit": 100})
    assert response.status_code == 422
    mock_embed_query.assert_not_called()


async def _noop_finalize(state) -> None:
    """Stand-in for the T3.4 finalize hook in tests that aren't exercising
    it directly — avoids a real Gemini call from the default-model variant
    generation agent that build_variant_engine() would otherwise build."""
    return None


def _stub_variant_hook(marker: dict):
    async def _hook(state) -> None:
        state.variants = [marker]

    return _hook


@patch("api.main.build_variant_engine")
@patch("agents.orchestrator.register_vector")
@patch("agents.orchestrator.get_connection")
@patch("agents.orchestrator.find_similar")
@patch("agents.orchestrator.embed_query")
def test_evaluate_endpoint_runs_end_to_end_with_registered_agents(
    mock_embed_query, mock_find_similar, mock_get_connection, mock_register_vector, mock_build_variant_engine
):
    """T3.2/T3.3: /evaluate wires registered agents into the orchestrator."""
    mock_embed_query.return_value = (np.zeros(3072, dtype=np.float32), 10)
    mock_find_similar.return_value = [fake_row("1"), fake_row("2")]
    mock_get_connection.return_value = MagicMock()
    mock_build_variant_engine.return_value = _noop_finalize

    predictor = _AgentStub({"predicted_engagement_percentile": 81.0, "predicted_total_engagement": 42})
    diagnostics = {"seo": _AgentStub({"score": 7.0})}

    with patch("api.main.predictor_agent", predictor), patch("api.main.diagnostic_agents", diagnostics):
        response = client.post("/api/v1/evaluate", json={"content": "Excited to announce our new product launch!"})

    assert response.status_code == 200
    body = response.json()
    assert body["draft_content"] == "Excited to announce our new product launch!"
    assert len(body["similar_posts"]) == 2
    assert body["predictor_result"] == {
        "predicted_engagement_percentile": 81.0,
        "predicted_total_engagement": 42,
    }
    assert body["diagnostics"] == {"seo": {"score": 7.0}}
    assert body["variants"] == []
    assert body["errors"] == []
    assert body["run_metadata"] is not None
    assert body["run_metadata"]["total_input_tokens"] >= 0
    assert len(body["run_metadata"]["steps"]) >= 1


@patch("api.main.build_variant_engine")
@patch("agents.orchestrator.register_vector")
@patch("agents.orchestrator.get_connection")
@patch("agents.orchestrator.find_similar")
@patch("agents.orchestrator.embed_query")
def test_evaluate_endpoint_passes_selected_variant_strategy(
    mock_embed_query, mock_find_similar, mock_get_connection, mock_register_vector, mock_build_variant_engine
):
    """T3.4: variant_strategy from the request body is forwarded to
    build_variant_engine(), and its resulting hook's output ends up in the
    response's `variants` field."""
    mock_embed_query.return_value = (np.zeros(3072, dtype=np.float32), 10)
    mock_find_similar.return_value = [fake_row("1")]
    mock_get_connection.return_value = MagicMock()
    mock_build_variant_engine.return_value = _stub_variant_hook({"strategy_label": "stub"})

    predictor = _AgentStub({"predicted_engagement_percentile": 81.0, "predicted_total_engagement": 42})
    diagnostics = {"seo": _AgentStub({"score": 7.0})}

    with patch("api.main.predictor_agent", predictor), patch("api.main.diagnostic_agents", diagnostics):
        response = client.post(
            "/api/v1/evaluate",
            json={"content": "Excited to announce our new product launch!", "variant_strategy": "tiered"},
        )

    assert response.status_code == 200
    assert response.json()["variants"] == [{"strategy_label": "stub"}]
    mock_build_variant_engine.assert_called_once()
    assert mock_build_variant_engine.call_args.kwargs["strategy"] == "tiered"
    assert mock_build_variant_engine.call_args.kwargs["reembed_neighbors"] is False


@patch("api.main.build_variant_engine")
@patch("agents.orchestrator.register_vector")
@patch("agents.orchestrator.get_connection")
@patch("agents.orchestrator.find_similar")
@patch("agents.orchestrator.embed_query")
def test_evaluate_endpoint_passes_reembed_variant_neighbors_flag(
    mock_embed_query, mock_find_similar, mock_get_connection, mock_register_vector, mock_build_variant_engine
):
    """T3.4: reembed_variant_neighbors from the request body is forwarded to
    build_variant_engine() as reembed_neighbors."""
    mock_embed_query.return_value = (np.zeros(3072, dtype=np.float32), 10)
    mock_find_similar.return_value = [fake_row("1")]
    mock_get_connection.return_value = MagicMock()
    mock_build_variant_engine.return_value = _stub_variant_hook({"strategy_label": "stub"})

    predictor = _AgentStub({"predicted_engagement_percentile": 81.0, "predicted_total_engagement": 42})
    diagnostics = {"seo": _AgentStub({"score": 7.0})}

    with patch("api.main.predictor_agent", predictor), patch("api.main.diagnostic_agents", diagnostics):
        response = client.post(
            "/api/v1/evaluate",
            json={"content": "Excited to announce our new product launch!", "reembed_variant_neighbors": True},
        )

    assert response.status_code == 200
    mock_build_variant_engine.assert_called_once()
    assert mock_build_variant_engine.call_args.kwargs["reembed_neighbors"] is True
    assert mock_build_variant_engine.call_args.kwargs["settings"] is not None


@patch("api.main.build_variant_engine")
@patch("agents.orchestrator.register_vector")
@patch("agents.orchestrator.get_connection")
@patch("agents.orchestrator.find_similar")
@patch("agents.orchestrator.embed_query")
def test_evaluate_endpoint_defaults_variant_strategy_to_dimension(
    mock_embed_query, mock_find_similar, mock_get_connection, mock_register_vector, mock_build_variant_engine
):
    mock_embed_query.return_value = (np.zeros(3072, dtype=np.float32), 10)
    mock_find_similar.return_value = [fake_row("1")]
    mock_get_connection.return_value = MagicMock()
    mock_build_variant_engine.return_value = _noop_finalize

    predictor = _AgentStub({"predicted_engagement_percentile": 81.0, "predicted_total_engagement": 42})
    diagnostics = {"seo": _AgentStub({"score": 7.0})}

    with patch("api.main.predictor_agent", predictor), patch("api.main.diagnostic_agents", diagnostics):
        response = client.post("/api/v1/evaluate", json={"content": "Excited to announce our new product launch!"})

    assert response.status_code == 200
    mock_build_variant_engine.assert_called_once()
    assert mock_build_variant_engine.call_args.kwargs["strategy"] == "dimension"


def test_evaluate_endpoint_empty_content_rejected():
    response = client.post("/api/v1/evaluate", json={"content": ""})
    assert response.status_code == 422


@patch("api.main.build_variant_engine")
@patch("agents.orchestrator.register_vector")
@patch("agents.orchestrator.get_connection")
@patch("agents.orchestrator.find_similar")
@patch("agents.orchestrator.embed_query")
def test_evaluate_endpoint_forwards_user_id_and_voice_profile_flag(
    mock_embed_query, mock_find_similar, mock_get_connection, mock_register_vector, mock_build_variant_engine
):
    """Personalization: user_id/use_voice_profile from the request body
    reach find_similar() (tenant-scoped retrieval) — the voice profile
    fetch itself is exercised directly in tests/test_orchestrator.py."""
    mock_embed_query.return_value = (np.zeros(3072, dtype=np.float32), 10)
    mock_find_similar.return_value = [fake_row("1")]
    mock_get_connection.return_value = MagicMock()
    mock_build_variant_engine.return_value = _noop_finalize

    predictor = _AgentStub({"predicted_engagement_percentile": 81.0, "predicted_total_engagement": 42})
    diagnostics = {"seo": _AgentStub({"score": 7.0})}

    with patch("api.main.predictor_agent", predictor), patch("api.main.diagnostic_agents", diagnostics):
        response = client.post(
            "/api/v1/evaluate",
            json={
                "content": "Excited to announce our new product launch!",
                "user_id": "user-42",
                "use_voice_profile": False,
            },
        )

    assert response.status_code == 200
    assert mock_find_similar.call_args.kwargs["user_id"] == "user-42"


def test_critique_endpoint_empty_content_rejected():
    response = client.post("/api/v1/critique", json={"content": ""})
    assert response.status_code == 422


@patch("api.main.run_audience_critic")
def test_critique_endpoint_returns_three_lenses(mock_run_audience_critic):
    """T7.11–T7.13: /critique is independent of the evaluate orchestrator."""
    from agents.audience_critic import (
        AudienceCriticOutput,
        CSuiteLens,
        PeerLens,
        PractitionerLens,
    )

    mock_run_audience_critic.return_value = AudienceCriticOutput(
        overall_verdict="Thin ROI case; weak tactics.",
        score=3.5,
        c_suite=CSuiteLens(
            reaction="Not convinced",
            primary_objection="No business outcome stated.",
            roi_notes="Buzzwords without numbers.",
        ),
        practitioner=PractitionerLens(
            reaction="Can't use this Monday",
            perceived_value="Low — no playbook.",
            tactical_gaps="Missing steps and owners.",
        ),
        peer=PeerLens(
            reaction="Familiar framing",
            credibility_check="Sounds like every other agency post.",
            originality_notes="No distinctive POV.",
        ),
    )

    response = client.post(
        "/api/v1/critique",
        json={"content": "Unlock synergy to drive digital transformation at scale."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["overall_verdict"].startswith("Thin ROI")
    assert body["score"] == 3.5
    assert body["c_suite"]["primary_objection"]
    assert body["practitioner"]["perceived_value"]
    assert body["peer"]["credibility_check"]
    mock_run_audience_critic.assert_called_once()
    assert "Unlock synergy" in mock_run_audience_critic.call_args.args[0]


def test_optimise_endpoint_empty_content_rejected():
    response = client.post("/api/v1/optimise", json={"content": ""})
    assert response.status_code == 422


@patch("api.main.run_synthesis")
def test_optimise_endpoint_returns_synthesis_result(mock_run_synthesis):
    """T7.14–T7.16: /optimise is independent of the evaluate orchestrator."""
    from agents.synthesis.schemas import (
        SynthesisRecommendation,
        SynthesisResult,
        SynthesisVariant,
    )

    mock_run_synthesis.return_value = SynthesisResult(
        variants=[
            SynthesisVariant(
                agent_id="maximizer",
                variant_name="Algorithmic Maximizer",
                optimized_text="Hook-first rewrite.",
                rationale="Stronger CTA.",
                predicted_engagement_percentile=80.0,
                predicted_total_engagement=120,
                delta_percentile=10.0,
            ),
            SynthesisVariant(
                agent_id="counter",
                variant_name="Strategic Counter",
                optimized_text="ROI-first rewrite.",
                rationale="Addresses CFO objections.",
                predicted_engagement_percentile=75.0,
                predicted_total_engagement=100,
                delta_percentile=5.0,
            ),
            SynthesisVariant(
                agent_id="brand_purist",
                variant_name="Brand Purist",
                optimized_text="Measured rewrite.",
                rationale="More credible tone.",
                predicted_engagement_percentile=70.0,
                predicted_total_engagement=90,
                delta_percentile=0.0,
            ),
        ],
        recommendation=SynthesisRecommendation(
            agent_id="maximizer",
            reason="Highest predicted engagement percentile (80).",
        ),
        baseline_percentile=70.0,
        critic_objection_used="No ROI proof.",
        errors=[],
    )

    response = client.post(
        "/api/v1/optimise",
        json={
            "content": "Unlock synergy at scale.",
            "primary_objection": "No ROI proof.",
            "baseline_percentile": 70.0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["variants"]) == 3
    assert body["recommendation"]["agent_id"] == "maximizer"
    assert body["critic_objection_used"] == "No ROI proof."
    mock_run_synthesis.assert_called_once()
    assert "Unlock synergy" in mock_run_synthesis.call_args.args[0]
