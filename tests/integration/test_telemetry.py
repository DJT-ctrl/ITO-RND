"""Telemetry wiring: API /metrics + Prometheus scrape of ito-api."""

from __future__ import annotations

import time

import httpx
import pytest


pytestmark = pytest.mark.integration


def test_api_metrics_endpoint_exposes_prometheus_text(http_client):
    # Touch a route so counters are non-empty after instrumentator scrape.
    http_client.get("/health")
    response = http_client.get("/metrics")
    assert response.status_code == 200, response.text
    text = response.text
    assert "http_requests" in text or "http_request" in text or "# HELP" in text


def test_prometheus_scrapes_ito_api(prometheus_base_url):
    """Wait for Prometheus scrape_interval (~15s) then assert target is up."""
    query_url = f"{prometheus_base_url}/api/v1/query"
    deadline = time.time() + 90
    last_payload = None
    while time.time() < deadline:
        response = httpx.get(query_url, params={"query": 'up{job="ito-api"}'}, timeout=10.0)
        assert response.status_code == 200, response.text
        last_payload = response.json()
        results = last_payload.get("data", {}).get("result", [])
        if results:
            value = results[0].get("value", [None, "0"])[1]
            if value == "1":
                return
        time.sleep(5)

    pytest.fail(
        f"Prometheus did not report up{{job=\"ito-api\"}}=1 within 90s. "
        f"Last payload: {last_payload}"
    )
