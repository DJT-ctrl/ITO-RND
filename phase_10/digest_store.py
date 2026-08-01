"""Postgres CRUD for agentic Pro digests (T10.10)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from phase_10.models import DigestRecord

_SEVERITIES = frozenset({"info", "warn", "critical"})


def _iso(created_at: Any) -> str:
    if isinstance(created_at, datetime):
        return created_at.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return str(created_at or "")


def _normalize_severity(raw: Any) -> str:
    value = str(raw or "info").strip().lower()
    if value in {"warning", "warn"}:
        return "warn"
    if value in _SEVERITIES:
        return value
    return "info"


def _row_to_record(
    digest_id: Any,
    created_at: Any,
    model: Any,
    summary: Any,
    severity: Any,
    payload: Any,
) -> DigestRecord:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return DigestRecord(
        id=str(digest_id),
        created_at=_iso(created_at),
        summary=str(summary or ""),
        model=str(model or "gemini-3.1-pro-preview"),
        severity=_normalize_severity(severity),
        payload=payload,
    )


def insert_digest(
    conn: psycopg.Connection,
    *,
    model: str,
    summary: str,
    severity: str = "info",
    payload: dict[str, Any] | None = None,
) -> DigestRecord:
    body = payload if isinstance(payload, dict) else {}
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agentic_digests (model, summary, severity, payload)
            VALUES (%s, %s, %s, %s)
            RETURNING id, created_at, model, summary, severity, payload
            """,
            (
                model,
                summary,
                _normalize_severity(severity),
                Jsonb(body),
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return _row_to_record(*row)


def list_digests(
    conn: psycopg.Connection,
    *,
    limit: int = 10,
) -> list[DigestRecord]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, created_at, model, summary, severity, payload
            FROM agentic_digests
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [_row_to_record(*row) for row in rows]
