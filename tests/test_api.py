"""Unit tests for api/main.py (T2: FastAPI + cosine-similarity retrieval).

Both embed_query() and find_similar() are patched — no real DB or Gemini
calls in unit tests, per repo convention (see tests/test_embedder.py and
tests/test_vector_store.py).
"""

from unittest.mock import MagicMock, patch

import numpy as np
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


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


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("api.main.register_vector")
@patch("api.main.get_connection")
@patch("api.main.find_similar")
@patch("api.main.embed_query")
def test_similar_posts_valid_request(mock_embed_query, mock_find_similar, mock_get_connection, mock_register_vector):
    mock_embed_query.return_value = np.zeros(3072, dtype=np.float32)
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


@patch("agents.orchestrator.register_vector")
@patch("agents.orchestrator.get_connection")
@patch("agents.orchestrator.find_similar")
@patch("agents.orchestrator.embed_query")
def test_evaluate_endpoint_runs_end_to_end_with_no_agents_registered(
    mock_embed_query, mock_find_similar, mock_get_connection, mock_register_vector
):
    """T3.1: no Predictor/Diagnostic agents exist yet (T3.2/T3.3), so this
    just proves the orchestrator runs end-to-end over HTTP — similar_posts
    populated, everything else at its empty placeholder default."""
    mock_embed_query.return_value = np.zeros(3072, dtype=np.float32)
    mock_find_similar.return_value = [fake_row("1"), fake_row("2")]
    mock_get_connection.return_value = MagicMock()

    response = client.post("/api/v1/evaluate", json={"content": "Excited to announce our new product launch!"})

    assert response.status_code == 200
    body = response.json()
    assert body["draft_content"] == "Excited to announce our new product launch!"
    assert len(body["similar_posts"]) == 2
    assert body["predictor_result"] is None
    assert body["diagnostics"] == {}
    assert body["variants"] == []
    assert body["errors"] == []


def test_evaluate_endpoint_empty_content_rejected():
    response = client.post("/api/v1/evaluate", json={"content": ""})
    assert response.status_code == 422
