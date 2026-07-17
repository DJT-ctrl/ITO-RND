"""Infra checks: migrate + health + schema (blame Docker/Postgres/schema on fail)."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def test_health_endpoint(http_client):
    response = http_client.get("/health")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok"}


def test_openapi_schema_loads(http_client):
    response = http_client.get("/openapi.json")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "paths" in body
    assert "/api/v1/similar-posts" in body["paths"]
    assert "/api/v1/evaluate" in body["paths"]


def test_posts_table_and_vector_extension_exist(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        assert cur.fetchone() is not None, "pgvector extension missing — migrate failed?"

        cur.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'posts'
            """
        )
        assert cur.fetchone() is not None, "posts table missing — migrate failed?"

        cur.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_name = 'posts' AND column_name = 'embedding'
            """
        )
        row = cur.fetchone()
        assert row is not None, "posts.embedding column missing"
