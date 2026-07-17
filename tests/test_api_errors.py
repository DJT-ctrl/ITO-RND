"""Tests for standardized API error envelope (issue #7)."""

import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
import psycopg
import pytest
from fastapi.testclient import TestClient
from google.genai import errors as genai_errors

from api.errors import ApiError, map_exception
from api.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_map_exception_value_error_missing_api_key():
    error = map_exception(ValueError("GEMINI_API_KEY is not set (check your .env file)."))
    assert error.code == "CONFIG_MISSING"
    assert error.status_code == 503
    assert error.retryable is False


def test_map_exception_provider_error_retryable():
    exc = genai_errors.APIError(503, {"error": {"message": "high demand"}})
    error = map_exception(exc)
    assert error.code == "PROVIDER_ERROR"
    assert error.status_code == 503
    assert error.retryable is True
    assert error.details["provider_status"] == 503


def test_map_exception_database_error():
    error = map_exception(psycopg.OperationalError("connection refused"))
    assert error.code == "DATABASE_UNAVAILABLE"
    assert error.status_code == 503
    assert error.retryable is True


@patch("api.main.embed_query")
def test_similar_posts_missing_api_key_returns_envelope(mock_embed_query):
    mock_embed_query.side_effect = ValueError("GEMINI_API_KEY is not set (check your .env file).")

    response = client.post(
        "/api/v1/similar-posts",
        json={"content": "Draft text for similarity search."},
    )

    assert response.status_code == 503
    body = response.json()
    assert body == {
        "code": "CONFIG_MISSING",
        "message": "Required AI provider configuration is missing.",
        "retryable": False,
        "details": {"config_key": "GEMINI_API_KEY"},
    }


@patch("api.main.get_connection")
@patch("api.main.embed_query")
def test_similar_posts_database_error_returns_envelope(mock_embed_query, mock_get_connection):
    mock_embed_query.return_value = (np.zeros(3072, dtype=np.float32), 10)
    mock_get_connection.side_effect = psycopg.OperationalError("connection refused")

    response = client.post(
        "/api/v1/similar-posts",
        json={"content": "Draft text for similarity search."},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "DATABASE_UNAVAILABLE"
    assert body["retryable"] is True
    assert body["details"]["error_type"] == "OperationalError"


@patch("api.main.embed_query")
def test_similar_posts_provider_error_returns_envelope(mock_embed_query):
    mock_embed_query.side_effect = genai_errors.APIError(502, {"error": {"message": "bad gateway"}})

    response = client.post(
        "/api/v1/similar-posts",
        json={"content": "Draft text for similarity search."},
    )

    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "PROVIDER_ERROR"
    assert body["retryable"] is True


def test_validation_error_keeps_422_envelope():
    response = client.post("/api/v1/similar-posts", json={"content": ""})
    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    assert isinstance(body["detail"], list)
    assert body["detail"][0]["loc"] == ["body", "content"]


@patch("api.main.run_evaluation_cycle")
@patch("api.main.build_variant_engine")
def test_evaluate_unhandled_error_returns_internal_envelope(mock_build_variant_engine, mock_run_evaluation_cycle):
    mock_build_variant_engine.return_value = MagicMock()
    mock_run_evaluation_cycle.side_effect = RuntimeError("unexpected orchestrator failure")

    response = client.post("/api/v1/evaluate", json={"content": "Draft text for evaluation."})

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["retryable"] is True
    assert body["message"] == "An unexpected error occurred."


def test_api_error_handler_returns_custom_envelope():
    from api.errors import api_error_handler

    error = ApiError(
        code="AGENT_UNAVAILABLE",
        message="Evaluation agents are not configured.",
        status_code=503,
        retryable=False,
        details={"component": "predictor"},
    )
    response = asyncio.run(api_error_handler(None, error))
    assert response.status_code == 503
    import json
    assert json.loads(response.body)["code"] == "AGENT_UNAVAILABLE"
