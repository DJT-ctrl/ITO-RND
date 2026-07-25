"""Shared Postgres connection helper for phase_10 stores."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from config.settings import Settings, load_settings
from storage.vector_store import create_schema, get_connection


class AgenticDbError(RuntimeError):
    """Raised when agentic Postgres access is unavailable."""


@contextmanager
def agentic_connection(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    settings = settings or load_settings()
    if not settings.database_url:
        raise AgenticDbError("DATABASE_URL is not set.")
    conn = get_connection(settings)
    try:
        create_schema(conn)
        yield conn
    finally:
        conn.close()
