"""Shared fixtures for docker-compose integration tests (issue #10)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import psycopg
import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SEED_META = json.loads((FIXTURES / "seed_meta.json").read_text(encoding="utf-8"))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: docker-compose end-to-end tests (issue #10)",
    )


@pytest.fixture(scope="session")
def api_base_url() -> str:
    return os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")


@pytest.fixture(scope="session")
def prometheus_base_url() -> str:
    return os.getenv("PROMETHEUS_BASE_URL", "http://localhost:9090").rstrip("/")


@pytest.fixture(scope="session")
def database_url() -> str:
    # Prefer process env (CI / ci-integration.sh). Avoid load_settings() here —
    # it reloads repo .env with override=True and would clobber CI DSNs.
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        pytest.fail("DATABASE_URL must be set for integration tests")
    return url


@pytest.fixture(scope="session")
def http_client(api_base_url: str):
    with httpx.Client(base_url=api_base_url, timeout=30.0) as client:
        yield client


@pytest.fixture(scope="session")
def db_conn(database_url: str):
    conn = psycopg.connect(database_url)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="session")
def seed_meta() -> dict:
    return SEED_META
