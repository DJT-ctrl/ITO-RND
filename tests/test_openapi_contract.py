"""OpenAPI contract tests for the v1 public API (issue #6)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.schemas import API_PATH_VERSION, API_VERSION

REPO_ROOT = Path(__file__).resolve().parents[1]
OPENAPI_SNAPSHOT = REPO_ROOT / "openapi.json"

client = TestClient(app)


@pytest.fixture
def openapi_spec() -> dict:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def test_openapi_info_metadata(openapi_spec: dict):
    info = openapi_spec["info"]
    assert info["title"] == "IntoTheOpen API"
    assert info["version"] == API_VERSION
    assert "Versioning" in info["description"]


def test_openapi_v1_paths_present(openapi_spec: dict):
    paths = openapi_spec["paths"]
    assert "/health" in paths
    assert "/api/v1/similar-posts" in paths
    assert "/api/v1/evaluate" in paths
    assert "/metrics" not in paths


def test_health_response_schema(openapi_spec: dict):
    schema_ref = (
        openapi_spec["paths"]["/health"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    )
    health_schema = _resolve_ref(openapi_spec, schema_ref)
    props = health_schema["properties"]
    status = props["status"]
    assert status.get("enum") == ["ok"] or status.get("const") == "ok"
    assert props["api_version"]["default"] == API_PATH_VERSION


def test_evaluate_response_is_typed(openapi_spec: dict):
    schema_ref = (
        openapi_spec["paths"]["/api/v1/evaluate"]["post"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
    )
    evaluate_schema = _resolve_ref(openapi_spec, schema_ref)
    props = evaluate_schema["properties"]

    predictor = _resolve_ref(openapi_spec, props["predictor_result"]["anyOf"][0])
    assert "predicted_engagement_percentile" in predictor["properties"]
    assert predictor["properties"]["predicted_engagement_percentile"]["type"] == "number"

    diagnostics = _resolve_ref(openapi_spec, props["diagnostics"])
    diagnostic_value = _resolve_ref(openapi_spec, diagnostics["additionalProperties"])
    assert "score" in diagnostic_value["properties"]

    variants = props["variants"]
    variant_item = _resolve_ref(openapi_spec, variants["items"])
    assert "variant_text" in variant_item["properties"]
    assert "additionalProperties" not in variant_item


def test_error_models_documented_on_post_routes(openapi_spec: dict):
    for path in ("/api/v1/similar-posts", "/api/v1/evaluate"):
        responses = openapi_spec["paths"][path]["post"]["responses"]
        assert "422" in responses
        assert "500" in responses
        error_schema = _resolve_ref(
            openapi_spec,
            responses["500"]["content"]["application/json"]["schema"],
        )
        assert "code" in error_schema["properties"]
        assert "retryable" in error_schema["properties"]


def test_openapi_snapshot_matches_runtime(openapi_spec: dict):
    assert OPENAPI_SNAPSHOT.is_file(), "Committed openapi.json missing — regenerate from app.openapi()"
    committed = json.loads(OPENAPI_SNAPSHOT.read_text(encoding="utf-8"))
    assert committed == openapi_spec


def test_health_endpoint_contract():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "api_version": API_PATH_VERSION}


def _resolve_ref(spec: dict, node: dict) -> dict:
    if "$ref" not in node:
        return node
    ref = node["$ref"]
    name = ref.rsplit("/", 1)[-1]
    return spec["components"]["schemas"][name]
