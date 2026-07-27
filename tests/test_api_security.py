"""Security tests for API auth, tenant boundaries, and rate limiting."""

from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from api.main import app
from api.rate_limit import limiter
from api.security import configure_api_security, parse_api_key_registry, rate_limit_identity
from config.settings import Settings


def _base_settings(**overrides) -> Settings:
    settings = Settings(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="fake-key",
        raw_data_dir="data/raw",
        default_search_limit=20,
        database_url="postgresql://fake/fake",
    )
    return replace(settings, **overrides)


def _sample_keys_json() -> str:
    return json.dumps(
        {
            "tenant-a-key": {"tenant_id": "tenant-a", "allowed_user_ids": ["user-42"]},
            "tenant-b-key": {"tenant_id": "tenant-b", "allowed_user_ids": ["user-99"]},
            "service-key": {"tenant_id": "internal", "allowed_user_ids": ["*"]},
        }
    )


@pytest.fixture
def auth_client(monkeypatch):
    """Enable API auth with a two-tenant key registry for security tests."""
    secured = _base_settings(
        api_auth_enabled=True,
        api_keys_json=_sample_keys_json(),
        api_rate_limit="",
    )
    monkeypatch.setattr("api.main.settings", secured)
    configure_api_security(secured)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_security_after_test():
    yield
    open_settings = _base_settings(api_auth_enabled=False, api_keys_json="", api_rate_limit="")
    configure_api_security(open_settings)


def test_parse_api_key_registry_accepts_service_wildcard():
    registry = parse_api_key_registry(
        json.dumps({"svc": {"tenant_id": "internal", "allowed_user_ids": ["*"]}})
    )
    assert registry["svc"].allowed_user_ids is None


def test_similar_posts_rejects_missing_auth_when_enabled(auth_client):
    response = auth_client.post(
        "/api/v1/similar-posts",
        json={"content": "Hello from tenant A", "limit": 5},
    )
    assert response.status_code == 401
    assert "Authorization" in response.json()["detail"]


def test_similar_posts_rejects_invalid_api_key(auth_client):
    response = auth_client.post(
        "/api/v1/similar-posts",
        json={"content": "Hello from tenant A", "limit": 5},
        headers={"Authorization": "Bearer not-a-real-key"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


@patch("api.main.register_vector")
@patch("api.main.get_connection")
@patch("api.main.find_similar")
@patch("api.main.embed_query")
def test_similar_posts_allows_authorized_tenant_user(
    mock_embed_query, mock_find_similar, mock_get_connection, mock_register_vector, auth_client
):
    mock_embed_query.return_value = (np.zeros(3072, dtype=np.float32), 10)
    mock_find_similar.return_value = []
    mock_get_connection.return_value = MagicMock()

    response = auth_client.post(
        "/api/v1/similar-posts",
        json={"content": "Hello from tenant A", "limit": 5, "user_id": "user-42"},
        headers={"Authorization": "Bearer tenant-a-key"},
    )

    assert response.status_code == 200
    assert mock_find_similar.call_args.kwargs["user_id"] == "user-42"


@patch("api.main.register_vector")
@patch("api.main.get_connection")
@patch("api.main.find_similar")
@patch("api.main.embed_query")
def test_similar_posts_blocks_cross_tenant_user_id(
    mock_embed_query, mock_find_similar, mock_get_connection, mock_register_vector, auth_client
):
    mock_embed_query.return_value = (np.zeros(3072, dtype=np.float32), 10)
    mock_get_connection.return_value = MagicMock()

    response = auth_client.post(
        "/api/v1/similar-posts",
        json={"content": "Attempting cross-tenant access", "limit": 5, "user_id": "user-99"},
        headers={"Authorization": "Bearer tenant-a-key"},
    )

    assert response.status_code == 403
    assert "user_id" in response.json()["detail"]
    mock_find_similar.assert_not_called()


@patch("api.main.build_variant_engine")
@patch("agents.orchestrator.register_vector")
@patch("agents.orchestrator.get_connection")
@patch("agents.orchestrator.find_similar")
@patch("agents.orchestrator.embed_query")
def test_evaluate_blocks_cross_tenant_user_id(
    mock_embed_query,
    mock_find_similar,
    mock_get_connection,
    mock_register_vector,
    mock_build_variant_engine,
    auth_client,
):
    mock_embed_query.return_value = (np.zeros(3072, dtype=np.float32), 10)
    mock_find_similar.return_value = []
    mock_get_connection.return_value = MagicMock()
    mock_build_variant_engine.return_value = lambda state: None

    response = auth_client.post(
        "/api/v1/evaluate",
        json={"content": "Cross-tenant evaluate attempt", "user_id": "user-99"},
        headers={"Authorization": "Bearer tenant-a-key"},
    )

    assert response.status_code == 403
    mock_find_similar.assert_not_called()


@patch("api.main.register_vector")
@patch("api.main.get_connection")
@patch("api.main.find_similar")
@patch("api.main.embed_query")
def test_service_key_allows_any_user_id(
    mock_embed_query, mock_find_similar, mock_get_connection, mock_register_vector, auth_client
):
    mock_embed_query.return_value = (np.zeros(3072, dtype=np.float32), 10)
    mock_find_similar.return_value = []
    mock_get_connection.return_value = MagicMock()

    response = auth_client.post(
        "/api/v1/similar-posts",
        json={"content": "Service account lookup", "limit": 5, "user_id": "user-99"},
        headers={"Authorization": "Bearer service-key"},
    )

    assert response.status_code == 200
    assert mock_find_similar.call_args.kwargs["user_id"] == "user-99"


def test_health_check_remains_unauthenticated_when_auth_enabled(auth_client):
    response = auth_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_rate_limit_enforced_per_api_key():
    from fastapi import FastAPI
    from slowapi.middleware import SlowAPIMiddleware

    probe_app = FastAPI()
    probe_limiter = limiter.__class__(key_func=rate_limit_identity)
    probe_app.state.limiter = probe_limiter
    probe_app.add_middleware(SlowAPIMiddleware)

    @probe_app.post("/probe")
    @probe_limiter.limit("2/minute")
    def _probe(request: Request):  # noqa: ARG001
        return {"ok": True}

    client = TestClient(probe_app)
    headers = {"Authorization": "Bearer tenant-a-key"}
    assert client.post("/probe", headers=headers).status_code == 200
    assert client.post("/probe", headers=headers).status_code == 200
    assert client.post("/probe", headers=headers).status_code == 429
